import asyncio
import json
import pytest
from datetime import timedelta
from test_provider_availability import make_store


def router_for(tmp_path, outcomes):
    from sophyane.rsi.coding_provider import CodingRouter
    store, clock = make_store(tmp_path)
    calls = []
    def factory(name, workspace, timeout):
        calls.append(name)
        outcome = outcomes[name]
        if isinstance(outcome, BaseException):
            raise outcome
        class Fake:
            def generate(self, prompt, system_prompt):
                return outcome
        return Fake()
    return CodingRouter(store, factory), clock, calls


GOOD = json.dumps({'files': {'value.py': 'VALUE = 2\n'}})


def test_success_only_codex_and_each_independent_request_restarts(tmp_path):
    router, clock, calls = router_for(tmp_path, {'codex_cli': GOOD})
    for _ in range(2):
        result = router.request('repair', tmp_path / 'candidate')
        assert result.provider == 'codex_cli'
        assert result.files == {'value.py': 'VALUE = 2\n'}
    assert calls == ['codex_cli', 'codex_cli']


@pytest.mark.parametrize('error', [RuntimeError('usage limit'), RuntimeError('quota'),
    TimeoutError(), FileNotFoundError(), RuntimeError('browser/CDP unavailable'),
    *[RuntimeError('HTTP ' + str(code)) for code in (429,500,502,503,504)]])
def test_eligible_failover_and_independent_nifdu(tmp_path, error):
    router, clock, calls = router_for(tmp_path, {'codex_cli': error, 'nifdu_browser': GOOD})
    assert router.request('repair', tmp_path / 'candidate').provider == 'nifdu_browser'
    assert calls == ['codex_cli', 'nifdu_browser']
    calls.clear()
    router.request('repair', tmp_path / 'candidate')
    assert calls == ['nifdu_browser']
    clock.value += timedelta(minutes=16)
    calls.clear()
    router.request('repair', tmp_path / 'candidate')
    assert calls == ['codex_cli', 'nifdu_browser']


@pytest.mark.parametrize('error', [TypeError('bug'), AssertionError('bug'),
    PermissionError('authority'), KeyboardInterrupt(), asyncio.CancelledError(),
    RuntimeError('schema bug'), RuntimeError('deterministic test failure')])
def test_terminal_errors_never_fail_over(tmp_path, error):
    router, clock, calls = router_for(tmp_path, {'codex_cli': error, 'nifdu_browser': GOOD})
    with pytest.raises(type(error)):
        router.request('repair', tmp_path / 'candidate')
    assert calls == ['codex_cli']


@pytest.mark.parametrize('link', ['__cause__', '__context__'])
@pytest.mark.parametrize('inner', [TypeError('bug'), AssertionError('bug'), PermissionError('denied')])
def test_wrapped_programming_and_authority_errors_remain_terminal(tmp_path, link, inner):
    outer = RuntimeError('transport connection failed')
    setattr(outer, link, inner)
    router, clock, calls = router_for(tmp_path, {'codex_cli': outer})
    with pytest.raises(RuntimeError):
        router.request('repair', tmp_path / 'candidate')
    assert calls == ['codex_cli']


def test_zero_exit_semantic_quota_and_no_local_or_gemini(tmp_path):
    router, clock, calls = router_for(tmp_path, {
        'codex_cli': RuntimeError('quota'),
        'nifdu_browser': {'exit_code': 0, 'output': 'ChatGPT usage limit reached\nNative Sophyane execution failed safely'},
        'local_gguf': GOOD, 'gemini': GOOD})
    result = router.request('repair', tmp_path / 'candidate')
    assert result.status == 'DEFERRED_NO_CODING_PROVIDER'
    assert result.files == {}
    assert calls == ['codex_cli', 'nifdu_browser']
    calls.clear()
    assert router.request('repair', tmp_path / 'candidate').status == 'DEFERRED_NO_CODING_PROVIDER'
    assert calls == []
    assert router.store.blocked('nifdu_browser')


def test_exact_retry_restores_codex_priority(tmp_path):
    router, clock, calls = router_for(tmp_path, {'codex_cli': GOOD, 'nifdu_browser': GOOD})
    router.store.failure('codex_cli', RuntimeError('usage limit reset at 19:00'))
    assert router.request('repair', tmp_path / 'candidate').provider == 'nifdu_browser'
    clock.value = clock.value.replace(hour=19)
    assert router.request('repair', tmp_path / 'candidate').provider == 'codex_cli'
    assert calls == ['nifdu_browser', 'codex_cli']


def test_plain_semantic_quota_is_availability_not_schema_failure(tmp_path):
    router,clock,calls=router_for(tmp_path,{'codex_cli':'usage limit reached','nifdu_browser':GOOD})
    assert router.request('repair',tmp_path/'candidate').provider == 'nifdu_browser'
    assert calls == ['codex_cli','nifdu_browser']


# SOPHYANE_CODING_ROUTER_OPERATION_AUTHORITY_RED_V1
def test_coding_router_can_request_ordinary_workspace_proposal_under_ordinary_authority(
    monkeypatch,
    tmp_path,
):
    """
    Proposal transport for an ordinary user workspace must not require
    Sophyane-source mutation authority.

    The provider still proposes bytes only; this contract grants no write,
    verification, approval, or promotion authority.
    """
    import sophyane.rsi.coding_provider as coding_provider
    from sophyane.rsi.authority import Operation

    workspace = (tmp_path / "ordinary-workspace").resolve()
    workspace.mkdir()

    authority_calls = []
    provider_calls = []

    class Store:
        def assert_external(self, candidate):
            assert candidate == workspace

        def blocked(self, provider):
            return False

        def probe(self, provider):
            pass

        def failure(self, provider, error):
            raise AssertionError(
                f"unexpected provider failure: {provider}: {error}"
            )

        def success(self, provider):
            pass

    class Provider:
        def generate(self, prompt, system):
            provider_calls.append(
                {
                    "prompt": prompt,
                    "system": system,
                }
            )
            return {
                "files": {
                    "capability.py": "VALUE = 1\n",
                }
            }

    def fake_require(provider, operation):
        authority_calls.append((provider, operation))

        assert operation is Operation.ORDINARY_WORKSPACE_MUTATION, (
            "ordinary workspace coding proposal incorrectly requested "
            "Sophyane-source mutation authority"
        )

    def factory(provider, requested_workspace, timeout):
        assert requested_workspace == workspace
        return Provider()

    monkeypatch.setattr(
        coding_provider,
        "require",
        fake_require,
    )

    router = coding_provider.CodingRouter(
        Store(),
        factory,
        operation=Operation.ORDINARY_WORKSPACE_MUTATION,
    )

    result = router.request(
        "Propose reusable parser support.",
        workspace,
    )

    assert result.status == "SUCCESS"
    assert result.files == {
        "capability.py": "VALUE = 1\n",
    }

    assert provider_calls

    assert authority_calls
    assert all(
        operation is Operation.ORDINARY_WORKSPACE_MUTATION
        for _, operation in authority_calls
    )


def test_coding_router_default_operation_remains_sophyane_source_mutation(
    monkeypatch,
    tmp_path,
):
    """
    Existing RSI callers that do not select an operation retain the original
    Sophyane-source authority contract.
    """
    import sophyane.rsi.coding_provider as coding_provider
    from sophyane.rsi.authority import Operation

    workspace = (tmp_path / "candidate").resolve()
    workspace.mkdir()

    authority_calls = []

    class Store:
        def assert_external(self, candidate):
            assert candidate == workspace

        def blocked(self, provider):
            return False

        def probe(self, provider):
            pass

        def failure(self, provider, error):
            raise AssertionError(
                f"unexpected provider failure: {provider}: {error}"
            )

        def success(self, provider):
            pass

    class Provider:
        def generate(self, prompt, system):
            return {
                "files": {
                    "src/sophyane/example.py": "VALUE = 1\n",
                }
            }

    def fake_require(provider, operation):
        authority_calls.append((provider, operation))

    def factory(provider, requested_workspace, timeout):
        return Provider()

    monkeypatch.setattr(
        coding_provider,
        "require",
        fake_require,
    )

    router = coding_provider.CodingRouter(
        Store(),
        factory,
    )

    result = router.request(
        "Propose Sophyane source repair.",
        workspace,
    )

    assert result.status == "SUCCESS"
    assert authority_calls
    assert all(
        operation is Operation.SOPHYANE_SOURCE_MUTATION
        for _, operation in authority_calls
    )
