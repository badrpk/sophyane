from dataclasses import replace
import json
import sys
import pytest
from conftest import git
from test_provider_failover import router_for, GOOD


def build_controller(repo, tmp_path, outcomes=None, **policy_changes):
    from sophyane.rsi.controller import Controller, Policy
    from sophyane.rsi.journal import Journal
    from sophyane.rsi.models import WeaknessRecord
    regression = ((sys.executable, 'regression.py'),)
    policy = Policy(targeted=regression, subsystem=regression, full_regression=regression,
        smoke=((sys.executable,'check.py'),),
        benchmark_command=(sys.executable,'-c','import json; from value import VALUE; print(json.dumps({"quality": VALUE, "latency": 1}))'),
        expected_failure='RSI_WEAKNESS_wrong_value', editable_paths=frozenset({'value.py'}),
        max_repair_rounds=2, max_lifecycle_seconds=30, command_timeout=5)
    policy = replace(policy, **policy_changes)
    router, clock, calls = router_for(tmp_path, outcomes or {'codex_cli': GOOD})
    controller = Controller(repo, tmp_path / 'candidates', router, Journal(tmp_path / 'audit'), policy)
    w = WeaknessRecord('wrong-value','known wrong value',('recorded assertion failure',),
        git(repo,'rev-parse','HEAD'),'quality',1,1,{'latency':{'direction':'lower','tolerance':0}},
        ((sys.executable,'check.py'),))
    return controller, w, calls


def test_complete_automatic_improvement_and_verified_baseline(repo, tmp_path):
    controller, w, calls = build_controller(repo, tmp_path)
    result = controller.run_once(w)
    assert result.state == 'VERIFIED_BASELINE'
    assert calls == ['codex_cli']
    assert git(repo,'rev-parse','HEAD') != w.baseline_commit
    assert (repo / 'value.py').read_text() == 'VALUE = 2\n'
    events = controller.journal.events()
    states = [x['state'] for x in events]
    for state in ('DETECTED','BASELINED','CANDIDATE_CREATED','RED_CONFIRMED','MODIFYING',
                  'VERIFYING','PROMOTION_READY','PROMOTING','PROMOTED','VERIFIED_BASELINE'):
        assert state in states
    assert all(event['iteration_id'] == result.iteration_id for event in events)
    assert not list((tmp_path / 'candidates').iterdir())
    second = controller.run_once(replace(w, baseline_commit=git(repo,'rev-parse','HEAD'), baseline_value=2),
                                 parent_iteration=result.iteration_id)
    assert second.state == 'REJECTED'  # Already GREEN cannot manufacture a new RED.


def test_end_to_end_post_promotion_rollback(repo, tmp_path):
    controller,w,calls = build_controller(repo,tmp_path,smoke=((sys.executable,'-c','raise RuntimeError("smoke failed")'),))
    result = controller.run_once(w)
    assert result.state == 'ROLLED_BACK'
    assert git(repo,'rev-parse','HEAD') == w.baseline_commit
    assert (repo/'value.py').read_bytes() == b'VALUE = 1\n'


def test_end_to_end_quota_uses_nifdu(repo, tmp_path):
    controller,w,calls = build_controller(repo,tmp_path,{'codex_cli':RuntimeError('usage limit'), 'nifdu_browser':GOOD})
    assert controller.run_once(w).state == 'VERIFIED_BASELINE'
    assert calls == ['codex_cli','nifdu_browser']


def test_end_to_end_no_coding_provider_defers_despite_local(repo,tmp_path):
    controller,w,calls = build_controller(repo,tmp_path,{'codex_cli':RuntimeError('quota'),
        'nifdu_browser':RuntimeError('quota'), 'local_gguf':GOOD})
    assert controller.run_once(w).state == 'DEFERRED_NO_CODING_PROVIDER'
    assert calls == ['codex_cli','nifdu_browser']
    assert git(repo,'rev-parse','HEAD') == w.baseline_commit


def test_end_to_end_local_mutation_attack_cannot_write(repo,tmp_path):
    from sophyane.rsi.coding_provider import CodingResult
    controller,w,calls = build_controller(repo,tmp_path)
    controller.router.request = lambda *a, **k: CodingResult('SUCCESS','local_gguf',{'value.py':'ATTACK'})
    with pytest.raises(PermissionError): controller.run_once(w)
    assert (repo/'value.py').read_text() == 'VALUE = 1\n'
    assert not list((tmp_path/'candidates').iterdir())


def test_no_action_cancel_and_repair_bound(repo,tmp_path):
    controller,w,calls = build_controller(repo,tmp_path,{'codex_cli':json.dumps({'files':{'value.py':'VALUE = 1\n'}})})
    assert controller.run_once(None).state == 'NO_ACTION'
    controller.cancelled = lambda: True
    assert controller.run_once(w).state == 'CANCELLED'
    assert calls == []
    controller.cancelled = lambda: False
    assert controller.run_once(w).state == 'REJECTED'
    assert calls == ['codex_cli','codex_cli']
    assert git(repo,'rev-parse','HEAD') == w.baseline_commit


def test_deadline_exhaustion_never_promotes(repo,tmp_path):
    controller,w,calls = build_controller(repo,tmp_path,max_lifecycle_seconds=.001)
    result = controller.run_once(w)
    assert result.state in ('CANCELLED','REJECTED')
    assert git(repo,'rev-parse','HEAD') == w.baseline_commit


def test_protected_metric_regression_rejects_passing_candidate(repo,tmp_path):
    controller,w,calls = build_controller(repo,tmp_path)
    w = replace(w, target_metric='latency', baseline_value=1, direction='lower',
                protected_metrics={'quality':{'direction':'lower','tolerance':0}})
    assert controller.run_once(w).state == 'REJECTED'
    assert git(repo,'rev-parse','HEAD') == w.baseline_commit


def test_benchmark_cannot_change_candidate_after_green(repo,tmp_path):
    controller,w,calls = build_controller(repo,tmp_path,benchmark_command=(sys.executable,'-c',
        'import json; from value import VALUE; from pathlib import Path; '
        'print(json.dumps({"quality":VALUE,"latency":1})); '
        'Path("value.py").write_text("VALUE = -99\\n") if VALUE == 2 else None'))
    with pytest.raises(PermissionError): controller.run_once(w)
    assert git(repo,'rev-parse','HEAD') == w.baseline_commit
    assert (repo/'value.py').read_text() == 'VALUE = 1\n'


def test_verification_script_cannot_be_in_editable_policy(repo,tmp_path):
    with pytest.raises(ValueError):
        build_controller(repo,tmp_path,editable_paths=frozenset({'value.py','regression.py'}))


def test_controller_rejects_concurrent_iteration(repo,tmp_path):
    import fcntl
    controller,w,calls=build_controller(repo,tmp_path)
    with (repo/'.git'/'sophyane-rsi-lifecycle.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError): controller.run_once(w)
    assert calls == []


def test_controller_recovers_unfinished_promotion_before_iteration(repo,tmp_path):
    from test_automatic_promotion import do_promote
    baseline,candidate,journal,result=do_promote(repo,tmp_path)
    controller,w,calls=build_controller(repo,tmp_path)
    controller.journal=journal
    journal.append('codex_cli','iteration-1','PROMOTING',{'checkpoint':str(result.checkpoint)})
    result=controller.run_once(replace(w,baseline_commit=baseline.commit))
    assert result.state == 'VERIFIED_BASELINE'
    assert any(e['iteration_id']=='iteration-1' and e['state']=='ROLLED_BACK' for e in journal.events())
    candidate.cleanup()


@pytest.mark.parametrize('editable,command', [
    ('other_check.py',(sys.executable,'./other_check.py')),
    ('tests/test_metric.py',(sys.executable,'-m','pytest','tests/test_metric.py::test_value')),
    ('tests/test_metric.py',(sys.executable,'-m','tests.test_metric')),
    ('tests/test_metric.py',(sys.executable,'-m','pytest','tests')),
    ('src/sophyane/rsi/authority.py',(sys.executable,'regression.py')),
    ('pyproject.toml',(sys.executable,'regression.py')),
])
def test_verification_policy_edit_aliases_are_denied(repo,tmp_path,editable,command):
    with pytest.raises(ValueError):
        build_controller(repo,tmp_path,editable_paths=frozenset({editable}),targeted=(command,))
