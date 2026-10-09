"""Trusted host transaction broker for bounded Sophyane RSI."""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from collections.abc import Mapping
import os
from pathlib import Path
import tempfile

from sophyane.repository_mutation_lease import repository_mutation_lease
from sophyane.intelligence_authority import provider_allowed_for_source_mutation
from .rsi.baseline import assert_baseline, git
from .rsi.benchmark import compare
from .rsi.coding_provider import CodingCancelled
from .rsi.verification import gates, passed, run_command


IMMUTABLE_TRUST_ROOTS = frozenset({
    "src/sophyane/intelligence_authority.py",
    "src/sophyane/rsi_host_broker.py",
})


@dataclass(frozen=True)
class PromotionResult:
    state: str
    checkpoint: Path | None = None
    smoke: tuple = ()


def _repository_identity(repository):
    common = Path(git(repository, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = Path(repository) / common
    return str(common.resolve())


def _validate_candidate(baseline, candidate, verification, mandatory):
    if not provider_allowed_for_source_mutation(candidate.record.provider_used):
        raise PermissionError("Only Codex/NIFDU providers may propose source mutation")
    candidate.assert_isolated()
    commit = candidate.record.candidate_commit
    if not commit:
        raise ValueError("Candidate has not been sealed")
    if git(candidate.path, "rev-parse", commit) != commit:
        raise ValueError("Sealed candidate commit is unavailable")
    parents = git(candidate.path, "rev-list", "--parents", "-n", "1", commit).split()
    if len(parents) != 2 or parents[1] != baseline.commit:
        raise ValueError("Sealed candidate parent differs from baseline")
    if git(candidate.path, "write-tree") != git(candidate.path, "rev-parse", commit + "^{tree}"):
        raise ValueError("Candidate changed after verification/sealing")
    if git(candidate.path, "diff", "--name-only"):
        raise ValueError("Candidate has unstaged changes after sealing")
    current_fingerprint = candidate.fingerprint()
    expected_fingerprint = (
        candidate.record.verified_fingerprint
        or getattr(candidate, "_sealed_fingerprint", None)
    )
    if expected_fingerprint is None or current_fingerprint != expected_fingerprint:
        raise ValueError("Candidate changed after verification")
    verified = tuple(getattr(verification, "changed_files", ()))
    changed_files = set(filter(None, git(
        candidate.path, "diff", "--name-only", baseline.commit, commit
    ).splitlines()))
    if changed_files & IMMUTABLE_TRUST_ROOTS:
        raise PermissionError("Candidate modifies immutable RSI trust root")
    if not all(mandatory.values()):
        raise ValueError("Mandatory deterministic gate failed")
    return commit


def _restore_checkpoint(evidence):
    repository = Path(evidence["repository"]).resolve()
    before, after = evidence["baseline_commit"], evidence["candidate_commit"]
    if _repository_identity(repository) != evidence["repository_identity"]:
        raise PermissionError("Rollback repository identity differs from checkpoint")
    head = git(repository, "rev-parse", "HEAD")
    if head not in (before, after):
        raise ValueError("Rollback refused: unrelated HEAD")
    if git(repository, "ls-files", "--others", "--exclude-standard"):
        raise ValueError("Rollback refused: unrelated untracked files")
    if git(repository, "diff", "--name-only"):
        raise ValueError("Rollback refused: unrelated working tree edits")
    index = git(repository, "write-tree")
    before_tree = git(repository, "rev-parse", before + "^{tree}")
    after_tree = git(repository, "rev-parse", after + "^{tree}")
    if index not in (before_tree, after_tree):
        raise ValueError("Rollback refused: unrelated index edits")
    if index == after_tree:
        git(repository, "read-tree", "-m", "-u", after, before)
    if head == after:
        git(repository, "update-ref", "HEAD", before, after)
    assert_baseline(repository, before)


def restore_checkpoint(evidence):
    repository = Path(evidence["repository"]).resolve()
    with repository_mutation_lease(repository):
        _restore_checkpoint(evidence)


def promote(baseline, candidate, weakness, verification, metrics, journal, iteration_id,
            *, smoke, failovers=(), parent_iteration=None, cancelled=lambda: False, timeout=300):
    provider = candidate.record.provider_used
    decision = compare(weakness, baseline.metrics, metrics)
    mandatory = gates(verification)
    if not decision.promote or not all(mandatory.values()) or not smoke:
        journal.append(provider, iteration_id, "REJECTED",
                       {"decision": decision, "gates": mandatory})
        return PromotionResult("REJECTED")
    if cancelled():
        raise CodingCancelled("Promotion cancelled")
    repository = Path(baseline.repository).resolve()
    if _repository_identity(repository) != baseline.repository_identity:
        raise PermissionError("Expected repository identity differs from baseline")
    if journal.root.is_relative_to(repository) or journal.root.is_relative_to(candidate.path):
        raise PermissionError("Audit state must remain outside worktrees")
    with repository_mutation_lease(repository):
        assert_baseline(repository, baseline.commit)
        commit = _validate_candidate(baseline, candidate, verification, mandatory)
        evidence = dict(
            iteration_id=iteration_id, parent_iteration=parent_iteration,
            repository=repository, repository_identity=baseline.repository_identity,
            baseline_commit=baseline.commit, candidate_commit=commit,
            weakness=weakness, baseline=baseline, verification=verification,
            baseline_metrics=baseline.metrics, candidate_metrics=metrics,
            promotion_decision=decision, gates=mandatory, provider_used=provider,
            failovers=failovers, timestamp=datetime.now().astimezone().isoformat(),
        )
        checkpoint = journal.checkpoint(provider, iteration_id, evidence)
        journal.append(provider, iteration_id, "PROMOTING", {"checkpoint": str(checkpoint)})
        results = ()
        try:
            if cancelled():
                raise CodingCancelled("Promotion cancelled")
            git(repository, "read-tree", "-m", "-u", baseline.commit, commit)
            git(repository, "update-ref", "HEAD", commit, baseline.commit)
            journal.append(provider, iteration_id, "PROMOTED", {"candidate_commit": commit})
            results = tuple(run_command(command, repository, timeout=timeout,
                                        cancelled=cancelled) for command in smoke)
            if not passed(results) or cancelled():
                raise CodingCancelled("Post-promotion smoke failed or cancelled")
            assert_baseline(repository, commit)
            journal.append(provider, iteration_id, "VERIFIED_BASELINE",
                           {"candidate_commit": commit, "post_promotion_smoke": results})
            return PromotionResult("VERIFIED_BASELINE", checkpoint, results)
        except BaseException as error:
            _restore_checkpoint(journal.load_checkpoint(checkpoint))
            journal.append(provider, iteration_id, "ROLLED_BACK",
                           {"checkpoint": str(checkpoint), "post_promotion_smoke": results,
                            "rollback_result": "restored recorded baseline", "error": str(error)})
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            return PromotionResult("ROLLED_BACK", checkpoint, results)


def recover_pending(journal, repository_identity):
    latest, checkpoints = {}, {}
    for event in journal.events():
        identifier = event["iteration_id"]
        if event["state"] in ("PROMOTING", "PROMOTED", "ROLLED_BACK", "VERIFIED_BASELINE"):
            latest[identifier] = event["state"]
        if event["evidence"].get("checkpoint"):
            checkpoints[identifier] = event["evidence"]["checkpoint"]
    recovered = []
    for identifier, state in latest.items():
        if state not in ("PROMOTING", "PROMOTED") or identifier not in checkpoints:
            continue
        evidence = journal.load_checkpoint(checkpoints[identifier])
        if evidence["repository_identity"] != str(repository_identity):
            continue
        restore_checkpoint(evidence)
        journal.append(evidence["provider_used"], identifier, "ROLLED_BACK",
                       {"checkpoint": checkpoints[identifier],
                        "rollback_result": "restored recorded baseline"})
        recovered.append(identifier)
    return recovered


def _snapshot_fingerprint(files):
    digest = hashlib.sha256()
    for name, value in sorted(files.items()):
        digest.update(name.encode() + b"\0" + hashlib.sha256(value).digest())
    return digest.hexdigest()


class SnapshotRecoveryError(RuntimeError):
    """Promotion failed and the broker could not prove restoration."""

    def __init__(self, message, evidence_path):
        super().__init__(f"{message}; recovery evidence: {evidence_path}")
        self.evidence_path = Path(evidence_path)


def _freeze_files(snapshot):
    files = getattr(snapshot, "files", snapshot)
    if not isinstance(files, Mapping):
        raise TypeError("snapshot files must be a mapping")
    frozen = {}
    for name, value in files.items():
        if not isinstance(name, str) or not name:
            raise ValueError("snapshot path must be a non-empty string")
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise TypeError("snapshot bytes must be bytes-like")
        frozen[name] = bytes(value)
    return frozen


def _canonical_snapshot_target(repository, name):
    if not isinstance(name, str) or not name or "\x00" in name:
        raise PermissionError("invalid snapshot path")
    path = Path(name)
    if path.is_absolute() or name in {".", ".."}:
        raise PermissionError("absolute or empty snapshot path")
    if any(part in {".", ".."} for part in path.parts):
        raise PermissionError("snapshot path traversal is forbidden")
    if os.path.normpath(name) != name or name.endswith((os.sep, "/")):
        raise PermissionError("snapshot path alias is forbidden")
    root = Path(repository).resolve(strict=True)
    destination = (root / path).resolve(strict=False)
    try:
        destination.relative_to(root)
    except ValueError as error:
        raise PermissionError("snapshot destination escapes repository") from error
    current = root
    for part in path.parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if current.is_symlink():
            raise PermissionError("snapshot symlink component is forbidden")
        if current == destination and current.is_file() and info.st_nlink > 1:
            raise PermissionError("snapshot hardlinked mutation target is forbidden")
    return destination


def _snapshot_state(target):
    if not target.exists() or target.is_symlink():
        return None
    if not target.is_file() or target.stat().st_nlink > 1:
        raise PermissionError("unsafe snapshot mutation target")
    return target.read_bytes()


def _write_snapshot_atomically(target, data):
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_recovery_evidence(repository, error, states):
    payload = {
        "repository": str(repository),
        "error": f"{type(error).__name__}: {error}",
        "states": {
            str(path): None if value is None else hashlib.sha256(value).hexdigest()
            for path, value in states.items()
        },
    }
    fd, name = tempfile.mkstemp(prefix="sophyane-snapshot-recovery-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    return Path(name)


def _restore_snapshot_states(states, *, owned_states=None):
    owned_states = {} if owned_states is None else dict(owned_states)
    for target, value in states.items():
        if target.is_symlink():
            raise PermissionError(f"snapshot restoration target is a symlink: {target}")
        if target.exists() and target.is_file() and target.stat().st_nlink > 1:
            raise PermissionError(f"snapshot restoration target is hardlinked: {target}")
        if target in owned_states and _snapshot_state(target) != owned_states[target]:
            raise PermissionError(
                f"snapshot restoration refused: transaction no longer owns target: {target}"
            )
        if value is None:
            if target.exists() or target.is_symlink():
                target.unlink()
        else:
            _write_snapshot_atomically(target, value)
    for target, value in states.items():
        if _snapshot_state(target) != value:
            raise ValueError(f"snapshot restoration verification failed: {target}")


@dataclass(frozen=True)
class SnapshotPromotion:
    repository: Path
    baseline: dict[str, bytes]
    candidate: dict[str, bytes]
    changed: tuple[str, ...]


def _load_live_candidate_snapshot(candidate_source):
    """Acquire one frozen live candidate snapshot at the trusted-host boundary."""
    from sophyane.rsi.candidate_workspace import snapshot
    return snapshot(Path(candidate_source))


def promote_snapshot(
    repository,
    baseline,
    candidate,
    evidence,
    allowed_paths,
    *,
    candidate_source=None,
):
    """Broker-owned promotion for legacy non-Git candidate snapshots."""
    repository = Path(repository).resolve()
    frozen_baseline = _freeze_files(baseline)
    evidence_fingerprint = str(getattr(evidence, "fingerprint", "") or "")
    with repository_mutation_lease(repository):
        if candidate_source is None:
            trusted_candidate = candidate
        else:
            trusted_candidate = _load_live_candidate_snapshot(candidate_source)

        frozen_candidate = _freeze_files(trusted_candidate)
        candidate_fingerprint = str(
            getattr(trusted_candidate, "fingerprint", "") or ""
        )

        if (
            not bool(getattr(evidence, "accepted", False))
            or evidence_fingerprint != candidate_fingerprint
        ):
            raise PermissionError("Snapshot lacks exact deterministic evidence")
        if _snapshot_fingerprint(frozen_candidate) != candidate_fingerprint:
            raise PermissionError("Candidate snapshot fingerprint mismatch")
        if _snapshot_fingerprint(frozen_baseline) != str(getattr(baseline, "fingerprint", "") or ""):
            raise PermissionError("Baseline snapshot fingerprint mismatch")
        baseline_targets = {name: _canonical_snapshot_target(repository, name) for name in frozen_baseline}
        candidate_targets = {name: _canonical_snapshot_target(repository, name) for name in frozen_candidate}
        changed = tuple(sorted(name for name in set(frozen_baseline) | set(frozen_candidate)
                               if frozen_baseline.get(name) != frozen_candidate.get(name)))
        if not changed or not set(changed) <= set(allowed_paths):
            raise PermissionError("Snapshot promotion scope is not verified")
        if any(name not in frozen_candidate for name in changed):
            raise PermissionError("Snapshot deletion promotion is forbidden")
        if set(changed) & IMMUTABLE_TRUST_ROOTS:
            raise PermissionError("Snapshot modifies immutable RSI trust root")
        current = {name: _snapshot_state(target) for name, target in baseline_targets.items()}
        if current != frozen_baseline:
            raise PermissionError("Primary snapshot changed since baseline")
        states = {candidate_targets[name]: current.get(name) for name in changed}
        written_states = {}
        promoted_states = {}
        try:
            for name in changed:
                target = _canonical_snapshot_target(repository, name)
                if _snapshot_state(target) != states[target]:
                    raise PermissionError("snapshot destination changed before mutation")
                _write_snapshot_atomically(target, frozen_candidate[name])
                written_states[target] = states[target]
                promoted_states[target] = frozen_candidate[name]
        except BaseException as error:
            try:
                _restore_snapshot_states(
                    written_states,
                    owned_states=promoted_states,
                )
            except BaseException as restore_error:
                evidence_path = _write_recovery_evidence(
                    repository, restore_error, written_states
                )
                raise SnapshotRecoveryError(
                    "snapshot restoration could not be proven",
                    evidence_path,
                ) from error
            raise
        for name in changed:
            if _snapshot_state(candidate_targets[name]) != frozen_candidate[name]:
                raise RuntimeError(f"snapshot promotion verification failed: {name}")
    return SnapshotPromotion(repository, dict(frozen_baseline), dict(frozen_candidate), changed)


def rollback_snapshot(transaction):
    """Restore a broker-owned snapshot promotion without trusting a provider."""
    with repository_mutation_lease(transaction.repository):
        frozen_baseline = _freeze_files(transaction.baseline)
        frozen_candidate = _freeze_files(transaction.candidate)
        try:
            targets = {name: _canonical_snapshot_target(transaction.repository, name) for name in transaction.changed}
        except PermissionError as error:
            raise ValueError("Snapshot rollback refused: unsafe destination") from error
        for name in transaction.changed:
            if _snapshot_state(targets[name]) != frozen_candidate.get(name):
                raise ValueError("Snapshot rollback refused: unrelated human change")
        states = {targets[name]: frozen_baseline.get(name) for name in transaction.changed}
        _restore_snapshot_states(states)
