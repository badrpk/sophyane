"""Deterministic, checkpointed local promotion with automatic smoke rollback."""
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from .authority import Operation, require
from .baseline import assert_baseline, git
from .benchmark import compare
from .coding_provider import CodingCancelled
from .rollback import restore_checkpoint, transaction_lock
from .verification import gates, passed, run_command


@dataclass(frozen=True)
class PromotionResult:
    state: str
    checkpoint: Path | None = None
    smoke: tuple = ()


def promote(baseline, candidate, weakness, verification, metrics, journal, iteration_id,
            *, smoke, failovers=(), parent_iteration=None, cancelled=lambda: False, timeout=300):
    provider = candidate.record.provider_used
    require(provider, Operation.PROMOTION_OPERATION)
    decision = compare(weakness, baseline.metrics, metrics)
    mandatory = gates(verification)
    if not decision.promote or not all(mandatory.values()) or not smoke:
        journal.append(provider, iteration_id, 'REJECTED', {'decision': decision, 'gates': mandatory})
        return PromotionResult('REJECTED')
    if cancelled():
        raise CodingCancelled('Promotion cancelled')
    if journal.root.is_relative_to(Path(baseline.repository)) or journal.root.is_relative_to(candidate.path):
        raise PermissionError('Audit state must remain outside worktrees')
    with transaction_lock(baseline.repository_identity):
        assert_baseline(baseline.repository, baseline.commit)
        candidate.assert_isolated()
        commit = candidate.record.candidate_commit
        if not commit:
            raise ValueError('Candidate has not been sealed')
        if git(candidate.path, 'write-tree') != git(candidate.path, 'rev-parse', commit + '^{tree}') or git(candidate.path, 'diff', '--name-only'):
            raise ValueError('Candidate changed after verification/sealing')
        evidence = dict(iteration_id=iteration_id, parent_iteration=parent_iteration,
            repository=baseline.repository, repository_identity=baseline.repository_identity,
            baseline_commit=baseline.commit, candidate_commit=commit, weakness=weakness,
            baseline=baseline, verification=verification, baseline_metrics=baseline.metrics,
            candidate_metrics=metrics, promotion_decision=decision, gates=mandatory,
            provider_used=provider, failovers=failovers, timestamp=datetime.now().astimezone().isoformat())
        checkpoint = journal.checkpoint(provider, iteration_id, evidence)
        # Retain immutable commit objects without touching remote branches.
        zero = '0' * len(baseline.commit)
        git(baseline.repository, 'update-ref', f'refs/sophyane-rsi/{iteration_id}/baseline', baseline.commit, zero)
        git(baseline.repository, 'update-ref', f'refs/sophyane-rsi/{iteration_id}/candidate', commit, zero)
        journal.append(provider, iteration_id, 'PROMOTING', {'checkpoint': str(checkpoint)})
        results = ()
        try:
            if cancelled():
                raise CodingCancelled('Promotion cancelled')
            git(baseline.repository, 'read-tree', '-m', '-u', baseline.commit, commit)
            git(baseline.repository, 'update-ref', 'HEAD', commit, baseline.commit)
            journal.append(provider, iteration_id, 'PROMOTED', {'candidate_commit': commit})
            results = tuple(run_command(command, baseline.repository, timeout=timeout, cancelled=cancelled) for command in smoke)
            if not passed(results) or cancelled():
                raise CodingCancelled('Post-promotion smoke failed or cancelled')
            assert_baseline(baseline.repository, commit)
            journal.append(provider, iteration_id, 'VERIFIED_BASELINE',
                           {'candidate_commit': commit, 'post_promotion_smoke': results})
            return PromotionResult('VERIFIED_BASELINE', checkpoint, results)
        except BaseException as error:
            restore_checkpoint(journal.load_checkpoint(checkpoint))
            journal.append(provider, iteration_id, 'ROLLED_BACK',
                           {'checkpoint': str(checkpoint), 'post_promotion_smoke': results,
                            'rollback_result': 'restored recorded baseline', 'error': str(error)})
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            return PromotionResult('ROLLED_BACK', checkpoint, results)
