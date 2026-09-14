from sophyane.rsi.experiment import ExperimentPlan, DeterministicExperimentRunner
from sophyane.rsi.models import CommandResult
from sophyane.rsi.campaign import RedStatus


def plan():
    return ExperimentPlan('bug', (('pytest', 'tests/test_bug.py'),),
                          (('pytest', 'tests/test_holdout.py'),),
                          (('pytest', 'tests/test_regression.py'),), 'wrong answer', frozenset({'engine.py'}))


def test_red_requires_repeatable_expected_assertion():
    runner = DeterministicExperimentRunner(lambda argv, path, **kw: CommandResult(argv, 1, 'AssertionError: wrong answer', str(path)))
    result = runner.red(plan(), '.')
    assert result.red_status == RedStatus.RED_CONFIRMED
    assert len(result.runs) == 2
    outputs = iter((1, 0))
    runner = DeterministicExperimentRunner(lambda argv, path, **kw: CommandResult(argv, next(outputs), 'AssertionError: wrong answer', str(path)))
    assert runner.red(plan(), '.').red_status == RedStatus.RED_FLAKY_OR_NONDETERMINISTIC


def test_preverifier_computes_green_and_rejects_holdout_and_protected_diff(tmp_path):
    from sophyane.rsi.candidate_workspace import CandidateWorkspace
    from sophyane.rsi.pre_verifier import DeterministicPreVerifier
    repo = tmp_path / 'repo'; repo.mkdir(); (repo / 'engine.py').write_text('bad')
    candidate = CandidateWorkspace(repo, tmp_path / 'scratch').create()
    red_runner = DeterministicExperimentRunner(lambda argv, path, **kw: CommandResult(argv, 1, 'AssertionError: wrong answer', str(path)))
    red = red_runner.red(plan(), candidate.path)
    candidate.apply('codex_cli', {'engine.py': 'good'}, {'engine.py'})
    runner = DeterministicExperimentRunner(lambda argv, path, **kw: CommandResult(argv, 0, '', str(path)))
    verifier = DeterministicPreVerifier(runner)
    assert verifier.verify(candidate, plan(), red).accepted
    runner.command_runner = lambda argv, path, **kw: CommandResult(argv, int('holdout' in str(argv)), '', str(path))
    assert not verifier.verify(candidate, plan(), red).accepted
    (candidate.path / 'tests').mkdir()
    (candidate.path / 'tests' / 'test_bug.py').write_text('assert True')
    evidence = verifier.verify(candidate, plan(), red)
    assert not evidence.accepted and 'scope' in evidence.reasons
    candidate.close()


def test_foreground_cancel_interrupts_verification_between_checks():
    calls = []
    runner = DeterministicExperimentRunner(lambda argv, path, **kw: calls.append(argv) or CommandResult(argv, 0, '', str(path)))
    runner.cancelled = lambda: len(calls) >= 1
    import pytest
    with pytest.raises(Exception, match='cancel'):
        runner.checks((('pytest', 'a'), ('pytest', 'b')), '.', 10)
    assert len(calls) == 1
