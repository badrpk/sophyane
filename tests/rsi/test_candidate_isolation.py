import os
import pytest
from conftest import git


def baseline_for(repo):
    from sophyane.rsi.baseline import capture
    return capture(repo, git(repo, 'rev-parse', 'HEAD'), {'quality': 1},
                   {'regression': {'command': ['python', 'regression.py'], 'exit_code': 0}})


def test_dirty_arbitrary_baseline_refused(repo):
    from sophyane.rsi.baseline import capture
    (repo / 'value.py').write_text('VALUE = 99\n')
    with pytest.raises(ValueError):
        baseline_for(repo)


def test_candidate_requested_head_independent_changes_reject_and_cleanup(repo, tmp_path):
    from sophyane.rsi.candidate import Candidate
    baseline = baseline_for(repo)
    before = (repo / 'value.py').read_bytes()
    candidate = Candidate.create(baseline, tmp_path / 'candidates')
    assert candidate.path != repo
    assert git(candidate.path, 'rev-parse', 'HEAD') == baseline.commit
    candidate.apply('codex_cli', {'value.py': 'VALUE = 2\n'}, {'value.py'})
    assert (candidate.path / 'value.py').read_text() == 'VALUE = 2\n'
    assert (repo / 'value.py').read_bytes() == before
    candidate.cleanup()
    assert not candidate.path.exists()
    assert (repo / 'value.py').read_bytes() == before
    assert git(repo, 'status', '--porcelain') == ''


@pytest.mark.parametrize('bad', ['../baseline/value.py', '.git/config', '/tmp/source', 'check.py'])
def test_invalid_replacement_batch_is_atomic(repo, tmp_path, bad):
    from sophyane.rsi.candidate import Candidate
    candidate = Candidate.create(baseline_for(repo), tmp_path / 'candidates')
    try:
        with pytest.raises(PermissionError):
            candidate.apply('codex_cli', {'value.py': 'changed', bad: 'attack'}, {'value.py'})
        assert (candidate.path / 'value.py').read_text() == 'VALUE = 1\n'
    finally:
        candidate.cleanup()


@pytest.mark.parametrize('link', ['symlink', 'hardlink'])
def test_link_escape_is_denied(repo, tmp_path, link):
    from sophyane.rsi.candidate import Candidate
    candidate = Candidate.create(baseline_for(repo), tmp_path / 'candidates')
    target = candidate.path / 'escape.py'
    if link == 'symlink': target.symlink_to(repo / 'value.py')
    else:
        import subprocess
        result = subprocess.run(['ln', str(repo / 'value.py'), str(target)], capture_output=True)
        if result.returncode:
            candidate.cleanup()
            pytest.skip('Platform prohibits creating hardlinks: ' + result.stderr.decode().strip())
    try:
        with pytest.raises(PermissionError):
            candidate.apply('nifdu_browser', {'escape.py': 'attack'}, {'escape.py'})
        assert (repo / 'value.py').read_text() == 'VALUE = 1\n'
    finally: candidate.cleanup()


def test_local_attack_no_file_changes_and_seal_retains_specific_tree(repo, tmp_path):
    from sophyane.rsi.candidate import Candidate
    candidate = Candidate.create(baseline_for(repo), tmp_path / 'candidates')
    try:
        with pytest.raises(PermissionError):
            candidate.apply('local_gguf', {'value.py': 'attack'}, {'value.py'})
        assert (candidate.path / 'value.py').read_text() == 'VALUE = 1\n'
        candidate.apply('nifdu_browser', {'value.py': 'VALUE = 2\n'}, {'value.py'})
        commit = candidate.seal()
        assert git(repo, 'show', commit + ':value.py') == 'VALUE = 2'
        assert git(repo, 'rev-parse', 'HEAD') == candidate.baseline.commit
    finally: candidate.cleanup()
