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
