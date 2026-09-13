import json
import pytest


def test_journal_is_persistent_and_checkpoint_immutable(tmp_path):
    from sophyane.rsi.journal import Journal
    journal = Journal(tmp_path / 'audit')
    journal.append('codex_cli', 'iteration-1', 'DETECTED', {'parent_iteration': None})
    checkpoint = journal.checkpoint('codex_cli', 'iteration-1', {'baseline_commit': 'a', 'candidate_commit': 'b'})
    with pytest.raises(FileExistsError):
        journal.checkpoint('codex_cli', 'iteration-1', {'baseline_commit': 'wrong'})
    reloaded = Journal(tmp_path / 'audit')
    assert reloaded.events()[0]['iteration_id'] == 'iteration-1'
    assert reloaded.events()[0]['timestamp']
    assert reloaded.load_checkpoint(checkpoint)['baseline_commit'] == 'a'
    value = json.loads(checkpoint.read_text()); value['evidence']['baseline_commit'] = 'tampered'
    checkpoint.chmod(0o600); checkpoint.write_text(json.dumps(value))
    with pytest.raises(ValueError): reloaded.load_checkpoint(checkpoint)


def test_local_cannot_write_journal_or_checkpoint(tmp_path):
    from sophyane.rsi.journal import Journal
    journal = Journal(tmp_path / 'audit')
    for write in (lambda: journal.append('local_gguf', 'id', 'PROMOTED', {}),
                  lambda: journal.checkpoint('local_gguf', 'id', {})):
        with pytest.raises(PermissionError): write()
    assert not (tmp_path / 'audit').exists()
