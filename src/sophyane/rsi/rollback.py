"""Restore recorded A using two-tree transitions, refusing unrelated changes."""
from contextlib import contextmanager
import fcntl
from pathlib import Path
from .authority import Operation, require
from .baseline import assert_baseline, git


@contextmanager
def transaction_lock(identity, *, name='sophyane-rsi.lock'):
    with (Path(identity) / name).open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def restore_checkpoint(evidence):
    repo = evidence['repository']
    before, after = evidence['baseline_commit'], evidence['candidate_commit']
    common = Path(git(repo, 'rev-parse', '--git-common-dir'))
    if not common.is_absolute(): common = Path(repo) / common
    if str(common.resolve()) != evidence['repository_identity']:
        raise PermissionError('Rollback repository identity differs from checkpoint')
    head = git(repo, 'rev-parse', 'HEAD')
    if head not in (before, after):
        raise ValueError('Rollback refused: unrelated HEAD')
    if git(repo, 'ls-files', '--others', '--exclude-standard'):
        raise ValueError('Rollback refused: unrelated untracked files')
    if git(repo, 'diff', '--name-only'):
        raise ValueError('Rollback refused: unrelated working tree edits')
    index = git(repo, 'write-tree')
    before_tree, after_tree = (git(repo, 'rev-parse', x + '^{tree}') for x in (before, after))
    if index not in (before_tree, after_tree):
        raise ValueError('Rollback refused: unrelated index edits')
    if index == after_tree:
        git(repo, 'read-tree', '-m', '-u', after, before)
    if head == after:
        git(repo, 'update-ref', 'HEAD', before, after)
    assert_baseline(repo, before)


def rollback(journal, checkpoint, *, provider):
    require(provider, Operation.ROLLBACK_OPERATION)
    evidence = journal.load_checkpoint(checkpoint)
    with transaction_lock(evidence['repository_identity']):
        restore_checkpoint(evidence)
        journal.append(provider, evidence['iteration_id'], 'ROLLED_BACK',
                       {'checkpoint': str(checkpoint), 'rollback_result': 'restored recorded baseline'})


def recover_pending(journal, repository_identity):
    """Recover unfinished transactions before a caller starts another iteration."""
    latest = {}
    checkpoints = {}
    for event in journal.events():
        identifier = event['iteration_id']
        if event['state'] in ('PROMOTING', 'PROMOTED', 'ROLLED_BACK', 'VERIFIED_BASELINE'):
            latest[identifier] = event['state']
        if event['evidence'].get('checkpoint'):
            checkpoints[identifier] = event['evidence']['checkpoint']
    recovered = []
    for identifier, state in latest.items():
        if state not in ('PROMOTING', 'PROMOTED'):
            continue
        checkpoint = checkpoints[identifier]
        evidence = journal.load_checkpoint(checkpoint)
        if evidence['repository_identity'] != str(repository_identity):
            continue
        rollback(journal, checkpoint, provider=evidence['provider_used'])
        recovered.append(identifier)
    return recovered
