"""Availability-aware, non-sticky coding proposal chain with no local fallback."""
import asyncio
from concurrent.futures import CancelledError
from dataclasses import dataclass, field
import json
from pathlib import Path

from sophyane.providers.human_conversation import availability_failure
from .availability import QUOTA
from .authority import CODING_PROVIDER_ORDER, Operation, require


class CodingCancelled(RuntimeError):
    pass


def eligible_failure(error):
    pending, seen = [error], set()
    while pending:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        if isinstance(item, (TypeError, AssertionError, PermissionError, KeyboardInterrupt,
                             asyncio.CancelledError, CancelledError, CodingCancelled, ValueError)):
            return False
        if any(word in str(item).lower() for word in
               ('cancel', 'schema', 'malformed', 'authority', 'isolation', 'test failure', 'programming')):
            return False
        pending.extend(x for x in (item.__cause__, item.__context__) if x is not None)
    return availability_failure(error) or (isinstance(error, RuntimeError) and bool(QUOTA.search(str(error))))


def create_provider(name, workspace, timeout):
    require(name, Operation.SOPHYANE_SOURCE_MUTATION)
    if name == 'codex_cli':
        from sophyane.providers.codex_cli import CodexCliProvider
        return CodexCliProvider(workspace=workspace, timeout=timeout)
    from sophyane.providers.nifdu_browser import NifduBrowserProvider
    return NifduBrowserProvider(timeout=timeout)


@dataclass(frozen=True)
class CodingResult:
    status: str
    provider: str = ''
    files: dict[str, str] = field(default_factory=dict)
    failovers: tuple[dict, ...] = ()


class CodingRouter:
    def __init__(self, store, factory=create_provider):
        self.store, self.factory = store, factory

    def request(self, prompt, workspace, *, cancelled=lambda: False, timeout=300):
        self.store.assert_external(workspace)
        failovers = []
        for name in CODING_PROVIDER_ORDER:
            if cancelled():
                raise CodingCancelled('Coding request cancelled')
            require(name, Operation.SOPHYANE_SOURCE_MUTATION)
            if self.store.blocked(name):
                failovers.append({'provider': name, 'reason': 'cooldown'})
                continue
            try:
                self.store.probe(name)
                provider = self.factory(name, Path(workspace), timeout)
                response = provider.generate(prompt, 'Return only JSON {"files": {"relative/path": "complete replacement"}}. '
                    'Propose edits only; do not execute commands or mutate files. No authority or approval decisions.')
                if cancelled():
                    raise CodingCancelled('Coding request cancelled')
                # A bridge's zero exit code is not semantic success.
                if isinstance(response, dict) and 'output' in response:
                    text = response['output']
                    if QUOTA.search(str(text)):
                        raise RuntimeError(str(text))
                    if response.get('exit_code', 0) != 0:
                        raise RuntimeError('Provider operation unsuccessful')
                    response = text
                if isinstance(response, str):
                    # Recognize failure messages before JSON parsing, not quota strings inside valid patches.
                    try:
                        payload = json.loads(response)
                    except json.JSONDecodeError:
                        payload = None
                    if payload is None:
                        if QUOTA.search(response):
                            raise RuntimeError(response)
                        raise ValueError('Malformed coding response schema')
                else:
                    payload = response
                if (not isinstance(payload, dict) or set(payload) != {'files'} or
                    not isinstance(payload['files'], dict) or not payload['files'] or
                    any(not isinstance(k, str) or not isinstance(v, str) for k, v in payload['files'].items())):
                    raise ValueError('Malformed coding response schema')
            except Exception as error:
                if cancelled():
                    raise CodingCancelled('Coding request cancelled') from error
                if not eligible_failure(error):
                    raise
                self.store.failure(name, error)
                failovers.append({'provider': name, 'reason': 'quota' if QUOTA.search(str(error)) else 'availability'})
                continue
            self.store.success(name)
            return CodingResult('SUCCESS', name, payload['files'], tuple(failovers))
        return CodingResult('DEFERRED_NO_CODING_PROVIDER', failovers=tuple(failovers))
