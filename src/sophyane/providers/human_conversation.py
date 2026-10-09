"""Request-local, bounded Mode-6 provider policy. No persisted routing state."""
from __future__ import annotations

import re
import subprocess
import time
from typing import Any, Callable, TypeVar
from urllib.error import HTTPError, URLError

from sophyane.providers.base import Provider, ProviderCandidateRejected, ProviderError, ProviderMetadata
from sophyane.runtime_cancel import cancelled
from sophyane.rsi.authority import CODING_PROVIDER_ORDER, ORDINARY_MUTATION_PROVIDER_ORDER, Operation, require

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

# Mode 6 has a deliberately bounded conversational failover contract.
# Global operational-provider activation does not implicitly extend this
# cascade. AGY remains independently selectable as an external provider.
MODE6_PROVIDER_ORDER = (
    "codex_cli",
    "nifdu_browser",
)
# One interactive Mode-6 request must reach a truthful bounded failure or
# failover before the terminal can be mistaken for a hung session.  This is
# the provider-invocation boundary used by both the initial conversation
# turn and the post-objective repository handoff.
MODE6_PROVIDER_TIMEOUT = 60
_T = TypeVar('_T')


class ProviderResponse(str):
    """Response text carrying immutable trusted runtime provider provenance."""

    def __setattr__(self, name, value):
        if hasattr(self, name):
            raise AttributeError("provider provenance is immutable")
        object.__setattr__(self, name, value)

    def __new__(cls, text, provider_id):
        value = super().__new__(cls, str(text))
        value.provider_id = str(provider_id)
        value.authorized_operations = frozenset(
            {"read_only", "ordinary_workspace_mutation"}
            | ({"source_mutation"} if value.provider_id in {"codex_cli", "nifdu_browser"} else set())
        )
        return value



def mode6_config() -> dict[str, Any]:
    """Read generation settings without initializing or persisting llm.json."""
    from sophyane.config import CONFIG_FILE, load_json

    config = load_json(CONFIG_FILE)
    configured_timeout = config.get('timeout', MODE6_PROVIDER_TIMEOUT)
    try:
        configured_timeout = int(configured_timeout)
    except (TypeError, ValueError):
        configured_timeout = MODE6_PROVIDER_TIMEOUT
    return {**config, 'provider': 'codex_cli', 'model': 'codex-default',
            'timeout': min(MODE6_PROVIDER_TIMEOUT, max(1, configured_timeout)),
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
            'failed to refresh token',
            'refresh token was revoked',
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
        configured_timeout = config.get('timeout', MODE6_PROVIDER_TIMEOUT)
        try:
            configured_timeout = int(configured_timeout)
        except (TypeError, ValueError):
            configured_timeout = MODE6_PROVIDER_TIMEOUT
        super().__init__('', 'codex-default',
                         min(MODE6_PROVIDER_TIMEOUT, max(1, configured_timeout)),
                         float(config.get('temperature', 0.3)),
                         int(config.get('max_tokens', 4096)))
        self.last_provider = ''
        self.last_errors: list[str] = []
        # Sanitized per-request provider route. Entries contain only
        # canonical provider identity and normalized state.
        self.last_provider_route: list[str] = []
        self._mutation_availability = None
        self.observer = None
        try:
            from sophyane.intelligence_observer import (
                default_intelligence_observer,
            )
            self.observer = default_intelligence_observer()
        except Exception:
            pass

    def _observe(self, **row: Any) -> None:
        observer = self.observer
        if observer is None:
            return
        try:
            observer.record_attempt(**row)
        except Exception:
            pass

    @property
    def chain(self) -> tuple[str, ...]:
        return MODE6_PROVIDER_ORDER

    def _create(self, name: str) -> Provider:
        from sophyane.providers.codex_cli import CodexCliProvider
        from sophyane.providers.nifdu_browser import NifduBrowserProvider

        from sophyane.intelligence_authority import assert_provider_allowed

        assert_provider_allowed(name)
        options = dict(timeout=self.timeout, temperature=self.temperature,
                       max_tokens=self.max_tokens)
        if name == 'codex_cli':
            return CodexCliProvider(model='codex-default', **options)
        if name == 'nifdu_browser':
            return NifduBrowserProvider(model='chatgpt-browser', **options)
        raise PermissionError(f'Mode-6 provider is not authorized: {name}')

    def run_request(self, request: Callable[[Provider], _T], *, image_path: str = '',
                    operation: Operation = Operation.READ_ONLY_OPERATION) -> _T:
        self.last_provider = ''
        self.last_errors = []
        self.last_provider_route = []
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

            attempt_started = time.perf_counter()
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

                self._observe(
                    provider=name,
                    transport=name,
                    model=str(getattr(locals().get('provider'), 'model', '') or ''),
                    operation=str(getattr(operation, 'value', operation)),
                    outcome='failure',
                    latency_seconds=time.perf_counter() - attempt_started,
                    failure_category=type(error).__name__,
                    diagnostic=str(error),
                )

                # SOPHYANE_MODE6_CANDIDATE_REJECTION_FAILOVER_V1
                #
                # A candidate rejection means transport succeeded but this
                # response is unusable for the current request. It may fall
                # through without changing persistent provider availability.
                candidate_rejected = isinstance(
                    error,
                    ProviderCandidateRejected,
                )

                if not candidate_rejected and not availability_failure(error):
                    raise

                route_state = (
                    'rejected'
                    if candidate_rejected
                    else 'unavailable'
                )
                self.last_provider_route.append(
                    f'{name}[{route_state}]'
                )
                errors.append(f'{name}: {type(error).__name__}: {error}')

                if (
                    not candidate_rejected
                    and name in {
                        'codex_cli',
                        'nifdu_browser',
                    }
                ):
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
            self.last_provider_route.append(
                f'{name}[success]'
            )
            self._observe(
                provider=name,
                transport=name,
                model=str(getattr(provider, 'model', '') or ''),
                operation=str(getattr(operation, 'value', operation)),
                outcome='success',
                latency_seconds=time.perf_counter() - attempt_started,
            )
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

        # SOPHYANE_MODE6_OPERATION_SCOPED_MUTATION_ORDER_V1
        # Mode 6 is cloud-only even when the lower-level RSI authority
        # permits local_gguf for ordinary workspace mutation in other contexts.
        # Keep that reusable RSI policy separate from this session policy.
        order = (
            tuple(
                name
                for name in ORDINARY_MUTATION_PROVIDER_ORDER
                if name in MODE6_PROVIDER_ORDER
            )
            if operation is Operation.ORDINARY_WORKSPACE_MUTATION
            else CODING_PROVIDER_ORDER
        )

        for name in order:
            require(name, operation)
            if cancelled():
                raise ProviderError('Mode-6 request cancelled')

            external_observation = name in CODING_PROVIDER_ORDER

            if external_observation and store.blocked(name):
                if (
                    name != "nifdu_browser"
                    or not store.revalidation_due(name)
                ):
                    self.last_errors.append(f'{name}: cooldown')
                    continue
            try:
                if external_observation:
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
                self.last_provider_route.append(
                    f'{name}[unavailable]'
                )
                if external_observation:
                    store.failure(name, error)
                self.last_errors.append(f'{name}: availability failure')
                continue
            if external_observation:
                store.success(name)
            self.last_provider = name
            self.last_provider_route.append(
                f'{name}[success]'
            )
            return result
        raise ProviderError('DEFERRED_NO_CODING_PROVIDER: ' + '; '.join(self.last_errors))

    def generate(self, prompt: str, system_prompt: str, *, image_path: str | None = None,
                 operation: Operation = Operation.READ_ONLY_OPERATION) -> str:
        def request(provider: Provider) -> str:
            if image_path:
                return provider.generate(prompt, system_prompt, image_path=image_path)
            return provider.generate(prompt, system_prompt)
        result = self.run_request(request, image_path=image_path or '', operation=operation)
        return ProviderResponse(result, self.last_provider)
