import sys
from conftest import git
from test_automatic_promotion import do_promote


def test_failed_fresh_smoke_restores_exact_prior_baseline(repo, tmp_path):
    old = git(repo, 'rev-parse', 'HEAD')
    before = {p.name:p.read_bytes() for p in repo.iterdir() if p.is_file()}
    baseline, candidate, journal, result = do_promote(repo, tmp_path,
        smoke=((sys.executable,'-c','raise RuntimeError("post-promotion failure")'),))
    assert result.state == 'ROLLED_BACK'
    assert git(repo,'rev-parse','HEAD') == old
    assert {p.name:p.read_bytes() for p in repo.iterdir() if p.is_file()} == before
    assert git(repo,'status','--porcelain') == ''
    assert 'post-promotion failure' in result.smoke[0].output
    assert journal.events()[-1]['state'] == 'ROLLED_BACK'
    candidate.cleanup()


def test_recovery_uses_recorded_checkpoint_not_llm(repo, tmp_path):
    from sophyane.rsi.rollback import rollback
    baseline, candidate, journal, result = do_promote(repo, tmp_path)
    rollback(journal, result.checkpoint, provider='codex_cli')
    assert git(repo, 'rev-parse', 'HEAD') == baseline.commit
    assert (repo / 'value.py').read_text() == 'VALUE = 1\n'
    candidate.cleanup()


def test_rollback_does_not_claim_clean_baseline_with_foreign_untracked_file(repo,tmp_path):
    import pytest
    from sophyane.rsi.rollback import rollback
    baseline,candidate,journal,result=do_promote(repo,tmp_path)
    (repo/'human.txt').write_text('unrelated human work')
    with pytest.raises(ValueError): rollback(journal,result.checkpoint,provider='codex_cli')
    assert (repo/'human.txt').read_text() == 'unrelated human work'


def test_unfinished_promotion_recovery_restores_checkpoint(repo,tmp_path):
    from sophyane.rsi.rollback import recover_pending
    baseline,candidate,journal,result=do_promote(repo,tmp_path)
    journal.append('codex_cli','iteration-1','PROMOTING',{'checkpoint':str(result.checkpoint)})
    assert recover_pending(journal,baseline.repository_identity) == ['iteration-1']
    assert git(repo,'rev-parse','HEAD') == baseline.commit
    assert journal.events()[-1]['state'] == 'ROLLED_BACK'
    assert recover_pending(journal,baseline.repository_identity) == []
    candidate.cleanup()


def test_generic_rejection_cannot_hide_unfinished_transaction(repo,tmp_path):
    from sophyane.rsi.rollback import recover_pending
    baseline,candidate,journal,result=do_promote(repo,tmp_path)
    journal.append('codex_cli','iteration-1','PROMOTING',{'checkpoint':str(result.checkpoint)})
    journal.append('codex_cli','iteration-1','REJECTED',{'reason':'Rollback failed transiently'})
    assert recover_pending(journal,baseline.repository_identity) == ['iteration-1']
    assert git(repo,'rev-parse','HEAD') == baseline.commit
    candidate.cleanup()
