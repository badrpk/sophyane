import pytest
from sophyane.rsi.candidate_workspace import CandidateWorkspace


def test_candidate_copies_dirty_bytes_and_cannot_touch_primary(tmp_path):
    repo = tmp_path / 'repo'; repo.mkdir()
    (repo / 'engine.py').write_text('dirty current state')
    candidate = CandidateWorkspace(repo, tmp_path / 'candidates').create()
    assert candidate.path != repo
    assert (candidate.path / 'engine.py').read_text() == 'dirty current state'
    candidate.apply('codex_cli', {'engine.py': 'fixed'}, {'engine.py'})
    assert (repo / 'engine.py').read_text() == 'dirty current state'
    assert candidate.diff().changed_files == ('engine.py',)
    with pytest.raises(PermissionError):
        candidate.apply('local_gguf', {'engine.py': 'AUTHORIZED=true'}, {'engine.py'})
    with pytest.raises(PermissionError):
        candidate.apply('codex_cli', {'../escape': 'x'}, {'../escape'})
    candidate.close()
    assert not candidate.path.exists()
    assert repo.exists()


def test_untrusted_preview_is_only_isolated_data_until_cloud_authorization(tmp_path):
    repo = tmp_path / 'repo'; repo.mkdir(); (repo / 'engine.py').write_text('original')
    candidate = CandidateWorkspace(repo, tmp_path / 'scratch').create()
    preview = getattr(candidate, 'preview', lambda files, paths: None)
    preview({'engine.py': 'proposal'}, {'engine.py'})
    assert (candidate.path / 'engine.py').read_text() == 'proposal'
    assert (repo / 'engine.py').read_text() == 'original'
    candidate.close()


def test_promotion_second_snapshot_must_match_verified_bytes(tmp_path, monkeypatch):
    import sophyane.rsi_host_broker as broker
    from sophyane.rsi.pre_verifier import VerificationEvidence

    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'engine.py').write_text('original')

    candidate = CandidateWorkspace(repo, tmp_path / 'scratch').create()
    candidate.preview({'engine.py': 'verified'}, {'engine.py'})

    # Evidence binds promotion to these independently verified candidate bytes.
    evidence = VerificationEvidence(True, candidate.diff().fingerprint)

    original = broker._load_live_candidate_snapshot
    calls = 0

    def racing(candidate_source):
        nonlocal calls
        calls += 1

        # Mutation occurs immediately before the trusted-host broker acquires
        # the live candidate snapshot used for promotion.
        if calls == 1:
            (candidate.path / 'engine.py').write_text('unverified')

        return original(candidate_source)

    monkeypatch.setattr(
        broker,
        '_load_live_candidate_snapshot',
        racing,
    )

    with pytest.raises(PermissionError):
        candidate.promote('codex_cli', evidence, {'engine.py'})

    assert calls == 1
    assert (repo / 'engine.py').read_text() == 'original'
    candidate.close()
