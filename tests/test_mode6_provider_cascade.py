"""Mode-6 routing uses canonical providers, with no live provider requests."""
import json
import os

import pytest

from sophyane.main import create_provider
from sophyane.providers.base import ProviderError

ORDER = ['codex_cli', 'nifdu_browser', 'local_gguf']


@pytest.fixture
def cascade(monkeypatch, tmp_path):
    from sophyane.providers import codex_cli, nifdu_browser, local_gguf
    from sophyane import config, runtime_cancel
    runtime_cancel.reset_cancel()
    monkeypatch.setenv('SOPHYANE_SESSION_MODE', 'human_conversation')
    monkeypatch.setenv('SOPHYANE_SESSION_PROVIDER', 'gemini')
    monkeypatch.setenv('SOPHYANE_SESSION_MODEL', 'stale-gemini-model')
    monkeypatch.setenv('XERUS_HOME', str(tmp_path / 'memory'))
    monkeypatch.setattr(config, 'save_config', lambda *_a, **_k: pytest.fail('config write'))
    monkeypatch.setattr(config, 'save_json', lambda *_a, **_k: pytest.fail('JSON write'))
    monkeypatch.setattr(config, 'ensure_default_llm_files', lambda: pytest.fail('llm.json initialization'))
    monkeypatch.setattr(local_gguf, 'load_gguf_runtime_state', lambda: {})
    calls, constructed, responses, prompts = [], [], {}, []
    for name, module, class_name in zip(ORDER, [codex_cli, nifdu_browser, local_gguf],
                                       ['CodexCliProvider', 'NifduBrowserProvider', 'LocalGgufProvider']):
        def factory(_name=name, **kwargs):
            constructed.append(_name)
            class Fake:
                model = kwargs.get('model', '')
                timeout = kwargs.get('timeout', 300)
                def generate(self, prompt, system_prompt, **options):
                    calls.append(_name)
                    prompts.append((prompt, options))
                    result = responses.get(_name, ['{"reply":"ok"}'])
                    value = result.pop(0) if len(result) > 1 else result[0]
                    if isinstance(value, BaseException):
                        raise value
                    if callable(value):
                        return value()
                    return value
            return Fake()
        monkeypatch.setattr(module, class_name, factory)
    saved = {'provider': 'gemini', 'model': 'saved-gemini', 'timeout': 30}
    monkeypatch.setattr(config, 'load_config', lambda: dict(saved))
    yield calls, constructed, responses, prompts, saved
    runtime_cancel.reset_cancel()


@pytest.mark.parametrize('failures', [0, 1, 2])
def test_order_success_and_request_restart(cascade, failures):
    calls, constructed, responses, _, saved = cascade
    before = dict(os.environ)
    for name in ORDER[:failures]:
        responses[name] = [ProviderError(name + ' temporarily unavailable')]
    provider = create_provider(saved)
    assert provider.generate('hello', '') == '{"reply":"ok"}'
    assert calls == ORDER[:failures + 1]
    assert 'gemini' not in constructed
    calls.clear()
    provider.generate('new independent request', '')
    assert calls == ORDER[:failures + 1]
    assert dict(os.environ) == before
    assert saved == {'provider': 'gemini', 'model': 'saved-gemini', 'timeout': 30}


@pytest.mark.parametrize('error', [KeyboardInterrupt(), ProviderError('request cancelled'),
    TypeError('programming bug'), AssertionError('bug'), PermissionError('authority violation'),
    ProviderError('invalid execution contract'), ProviderError('schema bug'),
    ProviderError('malformed internal action')])
def test_terminal_errors_never_switch(cascade, error):
    calls, constructed, responses, _, saved = cascade
    responses['codex_cli'] = [error]
    with pytest.raises(type(error)):
        create_provider(saved).generate('hello', '')
    assert calls == ['codex_cli']
    assert constructed == ['codex_cli']


def test_cancellation_state_never_switches(cascade):
    from sophyane.runtime_cancel import current_generation
    calls, constructed, responses, _, saved = cascade
    def cancel():
        current_generation().event.set()
        raise ProviderError('connection failed')
    responses['codex_cli'] = [cancel]
    with pytest.raises(ProviderError, match='cancel'):
        create_provider(saved).generate('hello', '')
    assert calls == constructed == ['codex_cli']


def test_all_unavailable_truthful(cascade):
    calls, constructed, responses, _, saved = cascade
    for name in ORDER:
        responses[name] = [ProviderError(name + ' connection failed')]
    with pytest.raises(ProviderError) as exc:
        create_provider(saved).generate('hello', '')
    assert calls == constructed == ORDER
    for name in ORDER:
        assert name + ' connection failed' in str(exc.value)
    assert 'gemini' not in str(exc.value).lower()


@pytest.mark.parametrize('status', [429, 500, 502, 503, 504])
def test_http_transport_failover(cascade, status):
    calls, _, responses, _, saved = cascade
    responses['codex_cli'] = [ProviderError(f'HTTP {status}')]
    create_provider(saved).generate('hello', '')
    assert calls == ORDER[:2]


@pytest.mark.parametrize('failures', [0, 1, 2])
def test_semantic_repair_stays_on_provider(cascade, failures):
    from sophyane.discovery_provider_reasoner import SessionProviderReasoner
    calls, _, responses, prompts, saved = cascade
    for name in ORDER[:failures]:
        responses[name] = [ProviderError('connection failed')]
    responses[ORDER[failures]] = ['{"action":{}}', '{"reply":"repaired"}']
    reasoner = SessionProviderReasoner(provider_factory=lambda: create_provider(saved))
    assert json.loads(reasoner('conversation_reply', {})) == {'reply': 'repaired'}
    assert calls == ORDER[:failures + 1] + [ORDER[failures]]
    assert 'SCHEMA_REPAIR_REQUEST' in prompts[-1][0]


def test_failed_semantic_repair_is_terminal(cascade):
    from sophyane.discovery_provider_reasoner import SessionProviderReasoner
    calls, _, responses, _, saved = cascade
    responses['codex_cli'] = ['{"action":{}}']
    reasoner = SessionProviderReasoner(provider_factory=lambda: create_provider(saved))
    with pytest.raises(RuntimeError, match='SCHEMA_VIOLATION'):
        reasoner('conversation_reply', {})
    assert calls == ['codex_cli', 'codex_cli']


def test_visual_transport_never_drops_image(cascade, tmp_path):
    from sophyane.discovery_provider_reasoner import SessionProviderReasoner
    calls, constructed, _, prompts, saved = cascade
    image = tmp_path / 'verified.jpg'
    image.write_bytes(b'camera fixture')
    reasoner = SessionProviderReasoner(provider_factory=lambda: create_provider(saved))
    reasoner('conversation_reply', {'_provider_image_path': str(image)})
    assert constructed == ORDER[:2]
    assert calls == ['nifdu_browser']
    assert prompts[0][1] == {'image_path': str(image)}
    assert str(image) not in prompts[0][0]


def test_repository_uses_same_cascade(cascade, monkeypatch, tmp_path):
    from sophyane.human_conversation_cli import _execute_repository_request
    calls, constructed, responses, _, _ = cascade
    for name in ORDER[:2]:
        responses[name] = [ProviderError('connection failed')]
    monkeypatch.setattr('sophyane.adaptive_execution.run_adaptive_loop',
                        lambda **kwargs: kwargs['ask']('next request'))
    assert _execute_repository_request('Inspect src/example.py', workspace=tmp_path)
    assert calls == ORDER + ORDER
    assert set(constructed) == set(ORDER)


def test_authority_is_bounded_even_with_stale_gemini(cascade):
    from sophyane.intelligence_authority import current_intelligence_authority, assert_provider_allowed
    authority = current_intelligence_authority()
    assert authority.session_provider == 'codex_cli'
    assert authority.provider_switching_allowed is False
    assert list(authority.provider_failover_order) == ORDER
    assert authority.bounded_provider_failover is True
    for name in ORDER:
        assert_provider_allowed(name)
    with pytest.raises(PermissionError):
        assert_provider_allowed('gemini')


@pytest.mark.parametrize('interactive', [True, False])
def test_startup_replaces_stale_authority_without_writes(cascade, monkeypatch, interactive):
    from sophyane import startup_policy as startup
    _, _, _, _, saved = cascade
    monkeypatch.setattr(startup.sys.stdin, 'isatty', lambda: interactive)
    monkeypatch.setattr('builtins.input', lambda *_: '6')
    monkeypatch.setattr(startup, 'load_config', lambda: dict(saved))
    monkeypatch.setattr(startup, '_load_llm', lambda: {})
    monkeypatch.setattr(startup, '_local_candidate', lambda *_: ('local_gguf', 'local'))
    monkeypatch.setattr(startup, '_configured_clouds', lambda: [])
    monkeypatch.setattr(startup, 'save_config', lambda *_: pytest.fail('persist config'))
    monkeypatch.setattr(startup, 'save_json', lambda *_: pytest.fail('persist llm'))
    result = startup.choose_startup_provider()
    assert result['provider'] == os.environ['SOPHYANE_SESSION_PROVIDER'] == 'codex_cli'
    assert result['model'] == os.environ['SOPHYANE_SESSION_MODEL'] == 'codex-default'
    assert result['provider_failover_order'] == ORDER


def test_default_reasoner_does_not_resolve_saved_provider(cascade, monkeypatch):
    from sophyane.discovery_provider_reasoner import SessionProviderReasoner
    monkeypatch.setattr('sophyane.main.run_setup_wizard',
                        lambda: pytest.fail('saved provider resolution / setup'))
    assert json.loads(SessionProviderReasoner()('conversation_reply', {})) == {'reply': 'ok'}
    assert cascade[0] == ['codex_cli']


def test_construction_failure_tries_next_canonical_provider(cascade, monkeypatch):
    def unavailable(**kwargs):
        raise ProviderError('Codex CLI executable was not found')
    monkeypatch.setattr('sophyane.providers.codex_cli.CodexCliProvider', unavailable)
    create_provider(cascade[-1]).generate('hello', '')
    assert cascade[0] == ['nifdu_browser']


@pytest.mark.parametrize('message', [
    'No ChatGPT Chromium tab found on CDP localhost:9222',
    'No responsive ChatGPT CDP target was found during readiness selection.',
    'ChatGPT usage limit reached; selected ChatGPT session cannot generate a new response',
])
def test_actual_nifdu_availability_diagnostics(cascade, message):
    calls, _, responses, _, saved = cascade
    responses['codex_cli'] = [ProviderError('Codex process unavailable')]
    responses['nifdu_browser'] = [RuntimeError(message)]
    create_provider(saved).generate('hello', '')
    assert calls == ORDER


def test_status_and_banner_do_not_advertise_gemini(cascade, monkeypatch):
    from sophyane.human_conversation import human_conversation_status
    from sophyane.cli_entry import _runtime_identity
    status = human_conversation_status()
    assert status['provider_failover_order'] == ORDER
    assert status['bounded_provider_failover'] is True
    assert status['provider_switching'] is False
    banner = _runtime_identity()
    assert 'gemini' not in banner.lower()
    assert ' -> '.join(ORDER) in banner


def test_default_conversation_never_initializes_llm_file(cascade, monkeypatch):
    from sophyane import config
    from sophyane.discovery_provider_reasoner import SessionProviderReasoner
    # The real generic reader initializes llm.json; Mode 6 must bypass it.
    monkeypatch.setattr(config, 'load_config',
                        lambda: pytest.fail('generic reader initializes llm.json'))
    assert json.loads(SessionProviderReasoner()('conversation_reply', {})) == {'reply': 'ok'}


def test_transport_failure_during_repair_restarts_original_request(cascade):
    from sophyane.discovery_provider_reasoner import SessionProviderReasoner
    calls, _, responses, prompts, saved = cascade
    responses['codex_cli'] = ['{"action":{}}', ProviderError('connection failed')]
    reasoner = SessionProviderReasoner(provider_factory=lambda: create_provider(saved))
    assert json.loads(reasoner('conversation_reply', {})) == {'reply': 'ok'}
    assert calls == ['codex_cli', 'codex_cli', 'nifdu_browser']
    assert 'SCHEMA_REPAIR_REQUEST' in prompts[1][0]
    assert 'SCHEMA_REPAIR_REQUEST' not in prompts[2][0]


@pytest.mark.parametrize('diagnostic', ['HTTP status 429', 'HTTP 503 Service Unavailable',
                                      'status code: 502 Bad Gateway'])
def test_http_status_diagnostics(cascade, diagnostic):
    calls, _, responses, _, saved = cascade
    responses['codex_cli'] = [ProviderError(diagnostic)]
    create_provider(saved).generate('hello', '')
    assert calls == ORDER[:2]


@pytest.mark.parametrize('error_name', ['WebSocketConnectionClosedException',
                                      'WebSocketTimeoutException', 'WebSocketAddressException'])
def test_nifdu_typed_connection_errors(cascade, error_name):
    websocket = pytest.importorskip('websocket')
    calls, _, responses, _, saved = cascade
    responses['codex_cli'] = [ProviderError('connection failed')]
    responses['nifdu_browser'] = [getattr(websocket, error_name)('CDP disconnected')]
    create_provider(saved).generate('hello', '')
    assert calls == ORDER


def test_mode6_codex_providererror_usage_limit_is_availability_failure():
    """Real Codex quota diagnostics are eligible Mode-6 availability failures."""
    from sophyane.providers.base import ProviderError
    from sophyane.providers.human_conversation import availability_failure

    error = ProviderError(
        'Codex CLI failed with status 1: '
        '{"type":"error","message":"You\'ve hit your usage limit. '
        'try again at 10:32 PM."}'
    )

    assert availability_failure(error) is True


def test_mode6_providererror_quota_failure_falls_through_to_next_provider():
    """A Codex ProviderError caused by quota must reach the next Mode-6 provider."""
    from sophyane.providers.base import ProviderError
    from sophyane.providers.human_conversation import HumanConversationProvider

    class FakeProvider:
        def __init__(self, name):
            self.provider_id = name

    provider = HumanConversationProvider()
    attempted = []

    def fake_create(name):
        attempted.append(name)
        return FakeProvider(name)

    provider._create = fake_create

    def request(candidate):
        if candidate.provider_id == "codex_cli":
            raise ProviderError(
                "Codex CLI failed with status 1: "
                "You've hit your usage limit. try again at 10:32 PM."
            )
        if candidate.provider_id == "nifdu_browser":
            return "answered-by-nifdu"
        raise AssertionError("local_gguf must not be reached")

    result = provider.run_request(request)

    assert result == "answered-by-nifdu"
    assert attempted == ["codex_cli", "nifdu_browser"]
    assert provider.last_provider == "nifdu_browser"
    assert provider.last_errors
    assert provider.last_errors[0].startswith("codex_cli:")



def test_mode6_local_conversation_uses_compact_request():
    """Local Mode-6 conversation fallback must not inherit discovery bulk."""
    from sophyane.discovery_provider_reasoner import (
        _mode6_candidate_request,
    )

    user_message = (
        "Tell me which provider actually answered this request. "
        "Do not modify any files."
    )

    huge_context = {
        "user_message": user_message,
        "conversation_context": {
            "thought": "X" * 9000,
            "perception": {"bulk": "Y" * 3000},
            "authority": {"bulk": "Z" * 2000},
        },
        "instructions": ["bulk " * 1000],
        "return_schema": {"reply": "string"},
    }

    original_prompt = "FULL_DISCOVERY_PROMPT:" + ("P" * 12000)
    original_system = "FULL_DISCOVERY_SYSTEM:" + ("S" * 4000)

    local_prompt, local_system = _mode6_candidate_request(
        provider_id="local_gguf",
        operation="conversation_reply",
        prompt=original_prompt,
        system_prompt=original_system,
        context=huge_context,
    )

    assert user_message in local_prompt
    assert "local_gguf" in local_prompt
    assert "X" * 100 not in local_prompt
    assert "Y" * 100 not in local_prompt
    assert "FULL_DISCOVERY_PROMPT" not in local_prompt
    assert "FULL_DISCOVERY_SYSTEM" not in local_system

    # Keep the ordinary short conversational fallback practical on slow
    # mobile prompt-prefill hardware.
    assert len(local_prompt) < 700
    assert len(local_system) < 300

    # Other providers retain the complete discovery request unchanged.
    for provider_id in ("codex_cli", "nifdu_browser"):
        cloud_prompt, cloud_system = _mode6_candidate_request(
            provider_id=provider_id,
            operation="conversation_reply",
            prompt=original_prompt,
            system_prompt=original_system,
            context=huge_context,
        )
        assert cloud_prompt == original_prompt
        assert cloud_system == original_system


def test_mode6_local_nonconversation_request_is_not_compacted():
    """Do not silently weaken non-conversation/structured operations."""
    from sophyane.discovery_provider_reasoner import (
        _mode6_candidate_request,
    )

    prompt = "ORIGINAL_PROMPT"
    system = "ORIGINAL_SYSTEM"

    result = _mode6_candidate_request(
        provider_id="local_gguf",
        operation="plan_experiment",
        prompt=prompt,
        system_prompt=system,
        context={"user_message": "ignored"},
    )

    assert result == (prompt, system)



def test_mode6_nifdu_exit_zero_quota_text_falls_through_to_local(monkeypatch):
    """Quota text returned with success status must fail over before repair."""
    import json

    from sophyane.discovery_provider_reasoner import (
        SessionProviderReasoner,
    )
    from sophyane.providers.base import ProviderError
    from sophyane.providers.human_conversation import (
        HumanConversationProvider,
    )

    calls = []

    class FakeProvider:
        def __init__(self, provider_id):
            self.provider_id = provider_id

        def generate(self, prompt, system_prompt, **kwargs):
            calls.append(self.provider_id)

            if self.provider_id == "codex_cli":
                raise ProviderError(
                    "You've hit your usage limit. "
                    "Please try again at 10:32 PM."
                )

            if self.provider_id == "nifdu_browser":
                # Real observed NIFDU behavior: browser/bridge may return
                # quota state as successful text instead of raising.
                return (
                    "ChatGPT usage limit reached; "
                    "wait for your usage to reset at 10:32 PM."
                )

            if self.provider_id == "local_gguf":
                return '''```json
{"reply":"local_gguf"}
```'''

            raise AssertionError(self.provider_id)

    cascade = HumanConversationProvider(
        {
            "timeout": 30,
            "temperature": 0,
            "max_tokens": 128,
        }
    )

    monkeypatch.setattr(
        cascade,
        "_create",
        lambda name: FakeProvider(name),
    )

    result = cascade.run_request(
        lambda candidate: SessionProviderReasoner._generate_response(
            candidate,
            "conversation_reply",
            "PROMPT",
            "SYSTEM",
            "",
        )
    )

    assert json.loads(result) == {
        "reply": "local_gguf",
    }

    # NIFDU quota must be classified before semantic repair; therefore
    # NIFDU receives exactly one generation attempt.
    assert calls == [
        "codex_cli",
        "nifdu_browser",
        "local_gguf",
    ]

    assert cascade.last_provider == "local_gguf"



def test_mode6_assigns_canonical_provider_id_before_request(monkeypatch):
    """Cascade identity must not depend on leaf provider implementation."""

    from sophyane.providers.human_conversation import (
        HumanConversationProvider,
    )

    created = []

    class ProviderWithoutIdentity:
        pass

    cascade = HumanConversationProvider()

    def create(name):
        created.append(name)

        # Simulate the real LocalGgufProvider behavior that exposed the bug:
        # the provider object itself does not define provider_id.
        candidate = ProviderWithoutIdentity()

        assert not hasattr(
            candidate,
            "provider_id",
        )

        return candidate

    monkeypatch.setattr(
        cascade,
        "_create",
        create,
    )

    # Skip the first two candidates without touching persistent state by
    # making their construction availability failures. The local candidate
    # must arrive at the callback with canonical identity attached.
    from sophyane.providers.base import ProviderError

    call_count = 0

    def create_with_failover(name):
        nonlocal call_count
        call_count += 1

        if name in {
            "codex_cli",
            "nifdu_browser",
        }:
            raise ProviderError(
                "connection unavailable"
            )

        return create(name)

    monkeypatch.setattr(
        cascade,
        "_create",
        create_with_failover,
    )

    seen = []

    result = cascade.run_request(
        lambda candidate: (
            seen.append(
                getattr(
                    candidate,
                    "provider_id",
                    None,
                )
            )
            or getattr(
                candidate,
                "provider_id",
                None,
            )
        )
    )

    assert result == "local_gguf"
    assert seen == ["local_gguf"]
    assert created == ["local_gguf"]
    assert cascade.last_provider == "local_gguf"


def test_mode6_canonical_identity_overrides_wrong_leaf_identity(monkeypatch):
    """The cascade route is authoritative, not a leaf's self-reported ID."""

    from sophyane.providers.base import ProviderError
    from sophyane.providers.human_conversation import (
        HumanConversationProvider,
    )

    class Candidate:
        provider_id = "wrong-provider"

    cascade = HumanConversationProvider()

    def create(name):
        if name in {
            "codex_cli",
            "nifdu_browser",
        }:
            raise ProviderError(
                "connection unavailable"
            )

        return Candidate()

    monkeypatch.setattr(
        cascade,
        "_create",
        create,
    )

    result = cascade.run_request(
        lambda candidate: candidate.provider_id
    )

    assert result == "local_gguf"
    assert cascade.last_provider == "local_gguf"


REPOSITORY_CAPABILITY_CASES = [
    ('Inspect src/example.py', 'read_only'),
    ('Read src/example.py', 'read_only'),
    ('Explain src/example.py', 'read_only'),
    ('Show me src/example.py', 'read_only'),
    ('List files in this repository', 'read_only'),
    ('Analyze src/example.py without changing it', 'read_only'),
    ('Analyze src/example.py without modifying it', 'read_only'),
    ('Inspect src/example.py; do not edit', 'read_only'),
    ('Perform read-only analysis of src/example.py', 'read_only'),
    ('Inspect src/example.py and fix the failing function', 'mutation'),
    ('List files and fix src/example.py', 'mutation'),
    ('Read src/example.py then patch the bug', 'mutation'),
    ('Analyze src/example.py and implement the fix', 'mutation'),
    ('Modify src/example.py', 'mutation'),
    ('Patch src/example.py', 'mutation'),
    ('Implement the missing function', 'mutation'),
    ('Inspect src/example.py without changing unrelated files and fix the bug', 'mutation'),
    ('Work on src/example.py', 'ambiguous'),
    ('Handle src/example.py', 'ambiguous'),
]


@pytest.mark.parametrize('request_text,expected', REPOSITORY_CAPABILITY_CASES)
def test_repository_capability(request_text, expected):
    from sophyane.request_classification import (
        RepositoryCapability, classify_repository_capability,
    )
    assert classify_repository_capability(request_text) is RepositoryCapability(expected)


def _assert_repository_defers(cascade, tmp_path, request_text):
    from sophyane.human_conversation_cli import _execute_repository_request
    calls, constructed, responses, _, _ = cascade
    for name in ORDER[:2]:
        responses[name] = [ProviderError('connection failed')]
    with pytest.raises(ProviderError, match='DEFERRED_NO_CODING_PROVIDER'):
        _execute_repository_request(request_text, workspace=tmp_path)
    assert calls == constructed == ORDER[:2]


def test_repository_mixed_mutation_defers(cascade, tmp_path):
    _assert_repository_defers(cascade, tmp_path,
                             'Inspect src/example.py and fix the failing function')


def test_repository_ambiguous_defers(cascade, tmp_path):
    _assert_repository_defers(cascade, tmp_path, 'Work on src/example.py')


@pytest.mark.parametrize('request_text,expected_operation', [
    ('Inspect src/example.py', 'read_only'),
    ('Modify src/example.py', 'source_mutation'),
])
def test_repository_repair_authority_stable(cascade, monkeypatch, tmp_path,
                                            request_text, expected_operation):
    from sophyane.human_conversation_cli import _execute_repository_request
    from sophyane.providers.human_conversation import HumanConversationProvider
    from sophyane.rsi.authority import Operation
    operations = []
    generate = HumanConversationProvider.generate

    def capture(self, *args, **kwargs):
        operations.append(kwargs['operation'])
        return generate(self, *args, **kwargs)

    monkeypatch.setattr(HumanConversationProvider, 'generate', capture)
    monkeypatch.setattr('sophyane.adaptive_execution.run_adaptive_loop',
                        lambda **kwargs: kwargs['ask'](
                            'Modify everything' if request_text.startswith('Inspect')
                            else 'Inspect only; do not edit'))
    assert _execute_repository_request(request_text, workspace=tmp_path)
    assert operations == [Operation(expected_operation)] * 2
