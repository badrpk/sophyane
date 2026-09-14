"""Request-local, bounded Mode-6 provider policy. No persisted routing state."""
from __future__ import annotations

import re
import subprocess
from typing import Any, Callable, TypeVar
from urllib.error import HTTPError, URLError

from sophyane.providers.base import Provider, ProviderError, ProviderMetadata
from sophyane.runtime_cancel import cancelled
from sophyane.rsi.authority import CODING_PROVIDER_ORDER, Operation, require

# websocket-client is optional for Codex/text-only installations.
try:
    from websocket import (
        WebSocketAddressException, WebSocketConnectionClosedException,
        WebSocketTimeoutException,
    )
except ImportError:
    _WEBSOCKET_TRANSPORT_ERRORS = ()
else:
    _WEBSOCKET_TRANSPORT_ERRORS = (
        WebSocketAddressException, WebSocketConnectionClosedException,
        WebSocketTimeoutException,
    )

_REQUEST_ERRORS = (ProviderError, RuntimeError, OSError, subprocess.TimeoutExpired) + _WEBSOCKET_TRANSPORT_ERRORS

from sophyane.intelligence_authority import ACTIVE_INTELLIGENCE_PROVIDERS

MODE6_PROVIDER_ORDER = ACTIVE_INTELLIGENCE_PROVIDERS
_T = TypeVar('_T')


def mode6_config() -> dict[str, Any]:
    """Read generation settings without initializing or persisting llm.json."""
    from sophyane.config import CONFIG_FILE, load_json

    config = load_json(CONFIG_FILE)
    return {**config, 'provider': 'codex_cli', 'model': 'codex-default',
            **mode6_status()}


def mode6_status() -> dict[str, Any]:
    return {
        'provider_failover_order': list(MODE6_PROVIDER_ORDER),
        'bounded_provider_failover': True,
    }


def availability_failure(error: BaseException) -> bool:
    """Allow transport failures only; contracts, bugs and cancellation terminate.

    The generic fallback's fatal-auth classifier and catch-all retry loop are
    deliberately unsuitable here. NIFDU's bridge also reports transport errors
    as RuntimeError, so only explicit transport diagnostics qualify.
    """
    # A provider may wrap a programming or authority error; do not disguise it
    # as availability merely because an outer diagnostic mentions transport.
    cause = error
    seen = set()
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if isinstance(cause, (TypeError, AssertionError, PermissionError, KeyboardInterrupt)):
            return False
        cause = cause.__cause__
    message = str(error).casefold()
    if any(word in message for word in (
        'cancel', 'keyboardinterrupt', 'schema', 'contract', 'malformed',
        'authority', 'assertion', 'typeerror', 'invalid action',
    )):
        return False
    if isinstance(error, _WEBSOCKET_TRANSPORT_ERRORS):
        return True
    if isinstance(error, HTTPError):
        return error.code in {429, 500, 502, 503, 504}
    if isinstance(error, (ConnectionError, TimeoutError, subprocess.TimeoutExpired)):
        return True
    if isinstance(error, URLError):
        return isinstance(error.reason, (ConnectionError, TimeoutError, OSError))
    if isinstance(error, FileNotFoundError):
        return True
    if not isinstance(error, (ProviderError, RuntimeError)):
        return False
    return bool(re.search(r'\b(?:http(?: error| status)?|status code)\s*[:=]?\s*(?:429|500|502|503|504)\b', message)) or any(
        marker in message for marker in (
            'unavailable', 'timed out', 'timeout', 'connection failed',
            'connection refused', 'connection reset', 'connection closed',
            'temporarily unavailable', 'temporary unavailable',
            'executable was not found', 'could not start',
            'browser bootstrap failed', 'browser failed to start',
            'callable selection is missing', 'bridge module is missing',
            'cdp disconnected', 'session not found', 'process exited',
            'no chatgpt chromium tab found', 'no responsive chatgpt cdp target',
            'browser verification challenge',
            'chatgpt usage limit reached',
            "you've hit your usage limit",
            'you have hit your usage limit',
            'usage limit reached',
        )
    )


class HumanConversationProvider(Provider):
    """Run one complete request per candidate, including same-provider repair.

    Providers are constructed lazily in fixed order. Neither a successful
    fallback nor a construction failure changes the next request's start.
    """
    metadata = ProviderMetadata(
        'human_conversation', 'Human Conversation', 'codex-default', '', False,
    )

    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        super().__init__('', 'codex-default', int(config.get('timeout', 300)),
                         float(config.get('temperature', 0.3)),
                         int(config.get('max_tokens', 4096)))
        self.last_provider = ''
        self.last_errors: list[str] = []
        self._mutation_availability = None

    @property
    def chain(self) -> tuple[str, ...]:
        return MODE6_PROVIDER_ORDER

    def _create(self, name: str) -> Provider:
        from sophyane.providers.codex_cli import CodexCliProvider
        from sophyane.providers.nifdu_browser import NifduBrowserProvider
        from sophyane.providers.local_gguf import LocalGgufProvider, load_gguf_runtime_state

        from sophyane.intelligence_authority import assert_provider_allowed

        assert_provider_allowed(name)
        options = dict(timeout=self.timeout, temperature=self.temperature,
                       max_tokens=self.max_tokens)
        if name == 'codex_cli':
            return CodexCliProvider(model='codex-default', **options)
        if name == 'nifdu_browser':
            return NifduBrowserProvider(model='chatgpt-browser', **options)
        if name == 'local_gguf':
            state = load_gguf_runtime_state()
            return LocalGgufProvider(
                model=str(state.get('model') or 'local-gguf'),
                endpoint=str(state.get('endpoint') or ''),
                gguf_path=str(state.get('gguf_path') or ''),
                cli_path=str(state.get('cli') or ''), **options,
            )
        raise PermissionError(f'Mode-6 provider is not authorized: {name}')

    def run_request(self, request: Callable[[Provider], _T], *, image_path: str = '',
                    operation: Operation = Operation.READ_ONLY_OPERATION) -> _T:
        self.last_provider = ''
        self.last_errors = []
        errors: list[str] = []
        require('codex_cli', operation)
        mutation = operation is not Operation.READ_ONLY_OPERATION
        if mutation:
            return self._run_mutation_request(request, operation, image_path)
        order = CODING_PROVIDER_ORDER if mutation else MODE6_PROVIDER_ORDER
        for name in order:
            require(name, operation)
            if cancelled():
                raise ProviderError('Mode-6 request cancelled')

            # SOPHYANE_MODE6_PERSISTENT_PROVIDER_AVAILABILITY_V1
            #
            # Known quota windows are external runtime observations, not
            # sticky provider preference. Each independent request still
            # starts from Codex logically, but skips providers whose observed
            # retry time has not arrived yet.
            if name in {
                'codex_cli',
                'nifdu_browser',
            }:
                from sophyane.providers.provider_availability import (
                    provider_block_info,
                )

                block = provider_block_info(
                    name
                )

                if block is not None:
                    retry_at = str(
                        block.get(
                            'retry_at',
                            '',
                        )
                        or ''
                    )

                    errors.append(
                        f'{name}: skipped until {retry_at}'
                    )

                    continue

            try:
                provider = self._create(name)

                # SOPHYANE_MODE6_CANONICAL_CANDIDATE_IDENTITY_V1
                #
                # The bounded cascade owns provider identity. Leaf provider
                # implementations are not required to expose provider_id
                # themselves (LocalGgufProvider currently does not). Attach
                # the authoritative route name before handing the candidate
                # to downstream Mode-6 request logic.
                provider.provider_id = name
                # Only the canonical NIFDU adapter declares image transport.
                # Never drop the pixels and ask a text provider to describe them.
                if image_path and name != 'nifdu_browser':
                    raise ProviderError(f'{name}: visual input transport unavailable')
                result = request(provider)
                if cancelled():
                    raise ProviderError('Mode-6 request cancelled')
            except _REQUEST_ERRORS as error:
                if cancelled():
                    raise ProviderError('Mode-6 request cancelled') from error
                if not availability_failure(error):
                    raise
                errors.append(f'{name}: {type(error).__name__}: {error}')

                if name in {
                    'codex_cli',
                    'nifdu_browser',
                }:
                    from sophyane.providers.provider_availability import (
                        record_availability_failure,
                    )

                    record_availability_failure(
                        name,
                        error,
                    )

                continue

            if name in {
                'codex_cli',
                'nifdu_browser',
            }:
                from sophyane.providers.provider_availability import (
                    record_provider_success,
                )

                record_provider_success(
                    name
                )

            self.last_provider = name
            self.last_errors = errors
            return result
        self.last_errors = errors
        message = 'DEFERRED_NO_CODING_PROVIDER' if mutation else 'All Mode-6 providers failed'
        raise ProviderError(message + ':\n- ' + '\n- '.join(errors))

    def _run_mutation_request(self, request, operation, image_path):
        from sophyane.rsi.availability import AvailabilityStore, QUOTA
        from sophyane.rsi.coding_provider import eligible_failure
        from sophyane.providers.provider_availability import state_path
        import json

        if self._mutation_availability is None:
            self._mutation_availability = AvailabilityStore(state_path())
        store = self._mutation_availability
        for name in CODING_PROVIDER_ORDER:
            require(name, operation)
            if cancelled():
                raise ProviderError('Mode-6 request cancelled')
            if store.blocked(name):
                if (
                    name != "nifdu_browser"
                    or not store.revalidation_due(name)
                ):
                    self.last_errors.append(f'{name}: cooldown')
                    continue
            try:
                store.probe(name)
                provider = self._create(name)
                provider.provider_id = name
                if image_path and name != 'nifdu_browser':
                    raise ProviderError('Visual input transport unavailable')
                result = request(provider)
                if cancelled():
                    raise ProviderError('Mode-6 request cancelled')
                text = result.get('output', '') if isinstance(result, dict) else result
                if isinstance(text, str):
                    valid_json = True
                    try:
                        json.loads(text)
                    except ValueError:
                        valid_json = False
                    if not valid_json and QUOTA.search(text):
                        raise ProviderError(text)
            except Exception as error:
                if cancelled() or not eligible_failure(error):
                    raise
                store.failure(name, error)
                self.last_errors.append(f'{name}: availability failure')
                continue
            store.success(name)
            self.last_provider = name
            return result
        raise ProviderError('DEFERRED_NO_CODING_PROVIDER: ' + '; '.join(self.last_errors))

    def generate(self, prompt: str, system_prompt: str, *, image_path: str | None = None,
                 operation: Operation = Operation.READ_ONLY_OPERATION) -> str:
        def request(provider: Provider) -> str:
            if image_path:
                return provider.generate(prompt, system_prompt, image_path=image_path)
            return provider.generate(prompt, system_prompt)
        return self.run_request(request, image_path=image_path or '', operation=operation)
