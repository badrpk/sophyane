from dataclasses import replace
import sys
import pytest
from conftest import git
from test_candidate_isolation import baseline_for
from test_benchmark_comparison import weakness
from test_verification_gate import passing_verification


def setup_candidate(repo, tmp_path):
    from sophyane.rsi.candidate import Candidate
    from sophyane.rsi.journal import Journal
    baseline = replace(baseline_for(repo), metrics={'quality':1,'latency':1})
    candidate = Candidate.create(baseline, tmp_path / 'candidates')
    candidate.apply('codex_cli', {'value.py':'VALUE = 2\n'}, {'value.py'})
    candidate.seal()
    journal = Journal(tmp_path / 'audit')
    w = replace(weakness(), baseline_commit=baseline.commit)
    return baseline, candidate, journal, w


def do_promote(repo, tmp_path, smoke=None, verification=None):
    from sophyane.rsi.promotion import promote
    baseline, candidate, journal, w = setup_candidate(repo, tmp_path)
    result = promote(baseline, candidate, w, verification or passing_verification(),
        {'quality':2,'latency':1}, journal, 'iteration-1',
        smoke=smoke or ((sys.executable,'check.py'),))
    return baseline, candidate, journal, result


def test_automatic_promotion_checkpoint_and_fresh_smoke(repo, tmp_path):
    baseline, candidate, journal, result = do_promote(repo, tmp_path)
    assert result.state == 'VERIFIED_BASELINE'
    assert git(repo, 'rev-parse', 'HEAD') == candidate.record.candidate_commit
    assert (repo / 'value.py').read_text() == 'VALUE = 2\n'
    checkpoint = journal.load_checkpoint(result.checkpoint)
    assert checkpoint['baseline_commit'] == baseline.commit
    assert checkpoint['candidate_commit'] == candidate.record.candidate_commit
    assert checkpoint['verification']['red']['exit_code'] == 1
    assert checkpoint['promotion_decision']['promote']
    assert checkpoint['provider_used'] == 'codex_cli'
    assert result.smoke[0].exit_code == 0
    candidate.cleanup()
    assert not candidate.path.exists()


def test_failed_gate_vetoes_even_with_good_benchmark(repo, tmp_path):
    baseline, candidate, journal, result = do_promote(repo, tmp_path,
        verification=replace(passing_verification(), full_regression=()))
    assert result.state == 'REJECTED'
    assert git(repo, 'rev-parse', 'HEAD') == baseline.commit
    candidate.cleanup()


def test_stale_or_dirty_baseline_never_overwritten(repo, tmp_path):
    from sophyane.rsi.promotion import promote
    baseline, candidate, journal, w = setup_candidate(repo, tmp_path)
    (repo / 'value.py').write_text('human work\n')
    with pytest.raises(ValueError):
        promote(baseline,candidate,w,passing_verification(),{'quality':2,'latency':1},
                journal,'iteration-1',smoke=((sys.executable,'check.py'),))
    assert (repo / 'value.py').read_text() == 'human work\n'
