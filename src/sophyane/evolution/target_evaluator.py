"""Isolated cross-BADRPK candidate evaluation.

V2C is intentionally NOT wired into EvolutionEngine.

Candidate patches are:

1. preflighted against TargetPolicy;
2. applied only to a detached disposable worktree;
3. validated there;
4. force-discarded afterwards.

No commit or promotion occurs.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .badrpk_targets import TargetSpec
from .target_policy import (
    TargetPolicy,
    build_target_policy,
)
from .target_validation import (
    DEFAULT_VALIDATION_TIMEOUT,
    ValidatorCheck,
    ValidatorRun,
    run_validators,
    verify_validators,
)
from .target_worktree import (
    abandon_target_worktree,
    create_target_worktree,
    target_head,
)
from .red_queen_policy import ChallengeRequest
from .trusted_supplemental_executor import (
    TrustedSupplementalResult,
    run_trusted_supplemental_challenges,
)


STATUS_PASS = "PASS"
STATUS_POLICY_REJECTED = "POLICY_REJECTED"
STATUS_PATCH_INVALID = "PATCH_INVALID"
STATUS_VALIDATION_UNAVAILABLE = "VALIDATION_UNAVAILABLE"
STATUS_VALIDATION_FAILED = "VALIDATION_FAILED"
STATUS_TARGET_DIRTY = "TARGET_DIRTY"
STATUS_INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True)
class CandidateEvaluation:
    status: str
    target_name: str
    source_head: str
    changed_paths: tuple[str, ...]
    validator_checks: tuple[ValidatorCheck, ...]
    validator_runs: tuple[ValidatorRun, ...]
    message: str

    @property
    def passed(self) -> bool:
        return self.status == STATUS_PASS


@dataclass(frozen=True)
class TrustedCandidateEvaluation:
    candidate: CandidateEvaluation
    supplemental: TrustedSupplementalResult | None

    @property
    def passed(self) -> bool:
        return (
            self.candidate.passed
            and self.supplemental is not None
            and self.supplemental.passed
        )


def _git(
    repo: Path,
    *args: str,
    input_bytes: bytes | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        (
            "git",
            "-C",
            str(repo),
            *args,
        ),
        input=input_bytes,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _target_clean(repo: Path) -> bool:
    completed = _git(
        repo,
        "status",
        "--porcelain",
    )

    return not completed.stdout.strip()


def _patch_paths(
    repo: Path,
    patch_path: Path,
) -> tuple[str, ...]:
    completed = _git(
        repo,
        "apply",
        "--numstat",
        "-z",
        str(patch_path),
        check=False,
    )

    if completed.returncode != 0:
        message = completed.stderr.decode(
            "utf-8",
            errors="replace",
        )

        raise ValueError(
            "git apply --numstat rejected patch: "
            + message.strip()
        )

    paths: list[str] = []

    for record in completed.stdout.split(b"\0"):
        if not record:
            continue

        fields = record.split(
            b"\t",
            2,
        )

        if len(fields) != 3:
            raise ValueError(
                "Unsupported git numstat record"
            )

        raw_path = fields[2]

        path = raw_path.decode(
            "utf-8",
            errors="strict",
        )

        candidate = Path(path)

        if candidate.is_absolute():
            raise ValueError(
                f"Absolute patch path rejected: {path}"
            )

        if ".." in candidate.parts:
            raise ValueError(
                f"Escaping patch path rejected: {path}"
            )

        paths.append(path)

    if not paths:
        raise ValueError(
            "Patch contains no changed paths"
        )

    return tuple(
        dict.fromkeys(paths)
    )


def _policy_rejections(
    policy: TargetPolicy,
    paths: tuple[str, ...],
) -> tuple[str, ...]:
    rejected: list[str] = []

    for relative in paths:
        candidate = (
            policy.repo
            / relative
        )

        if not policy.path_is_mutable(
            candidate
        ):
            rejected.append(relative)

    return tuple(rejected)


def _actual_changed_paths(
    worktree: Path,
) -> tuple[str, ...]:
    completed = _git(
        worktree,
        "diff",
        "--name-only",
        "-z",
        "HEAD",
    )

    paths = [
        item.decode(
            "utf-8",
            errors="strict",
        )
        for item in completed.stdout.split(b"\0")
        if item
    ]

    return tuple(paths)


def _evaluate_candidate_patch(
    target: TargetSpec,
    patch: str | bytes,
    *,
    timeout: int = DEFAULT_VALIDATION_TIMEOUT,
    _on_validated_worktree: Callable[[Path], None] | None = None,
) -> CandidateEvaluation:
    """Evaluate a unified git patch without mutating target HEAD."""

    source_head = target_head(target)

    if not _target_clean(target.repo):
        return CandidateEvaluation(
            status=STATUS_TARGET_DIRTY,
            target_name=target.name,
            source_head=source_head,
            changed_paths=(),
            validator_checks=(),
            validator_runs=(),
            message=(
                "Target worktree is dirty; "
                "V2C refuses ambiguous evaluation"
            ),
        )

    policy = build_target_policy(target)

    payload = (
        patch.encode("utf-8")
        if isinstance(patch, str)
        else bytes(patch)
    )

    patch_file: Path | None = None
    worktree = None

    try:
        with tempfile.NamedTemporaryFile(
            prefix="sophyane-v2c-",
            suffix=".patch",
            delete=False,
        ) as handle:
            handle.write(payload)
            patch_file = Path(
                handle.name
            )

        try:
            paths = _patch_paths(
                target.repo,
                patch_file,
            )
        except (
            UnicodeDecodeError,
            ValueError,
        ) as error:
            return CandidateEvaluation(
                status=STATUS_PATCH_INVALID,
                target_name=target.name,
                source_head=source_head,
                changed_paths=(),
                validator_checks=(),
                validator_runs=(),
                message=str(error),
            )

        rejected = _policy_rejections(
            policy,
            paths,
        )

        if rejected:
            return CandidateEvaluation(
                status=STATUS_POLICY_REJECTED,
                target_name=target.name,
                source_head=source_head,
                changed_paths=paths,
                validator_checks=(),
                validator_runs=(),
                message=(
                    "Patch touches non-mutable paths: "
                    + ", ".join(rejected)
                ),
            )

        worktree = create_target_worktree(
            target
        )

        if target_head(target) != source_head:
            raise RuntimeError(
                "Target HEAD changed while "
                "candidate evaluator was starting"
            )

        check_patch = _git(
            worktree.path,
            "apply",
            "--check",
            str(patch_file),
            check=False,
        )

        if check_patch.returncode != 0:
            message = check_patch.stderr.decode(
                "utf-8",
                errors="replace",
            ).strip()

            return CandidateEvaluation(
                status=STATUS_PATCH_INVALID,
                target_name=target.name,
                source_head=source_head,
                changed_paths=paths,
                validator_checks=(),
                validator_runs=(),
                message=message,
            )

        checks = verify_validators(
            worktree.path,
            policy.validators,
        )

        if not checks:
            return CandidateEvaluation(
                status=STATUS_VALIDATION_UNAVAILABLE,
                target_name=target.name,
                source_head=source_head,
                changed_paths=paths,
                validator_checks=(),
                validator_runs=(),
                message=(
                    "No validators discovered "
                    "for target"
                ),
            )

        unavailable = tuple(
            check
            for check in checks
            if not check.runnable
        )

        if unavailable:
            detail = "; ".join(
                f"{check.spec.name}: "
                f"{check.reason}"
                for check in unavailable
            )

            return CandidateEvaluation(
                status=STATUS_VALIDATION_UNAVAILABLE,
                target_name=target.name,
                source_head=source_head,
                changed_paths=paths,
                validator_checks=checks,
                validator_runs=(),
                message=(
                    "Not all discovered validators "
                    "are runnable: "
                    + detail
                ),
            )

        apply_patch = _git(
            worktree.path,
            "apply",
            str(patch_file),
            check=False,
        )

        if apply_patch.returncode != 0:
            message = apply_patch.stderr.decode(
                "utf-8",
                errors="replace",
            ).strip()

            return CandidateEvaluation(
                status=STATUS_PATCH_INVALID,
                target_name=target.name,
                source_head=source_head,
                changed_paths=paths,
                validator_checks=checks,
                validator_runs=(),
                message=message,
            )

        actual = _actual_changed_paths(
            worktree.path
        )

        if set(actual) != set(paths):
            return CandidateEvaluation(
                status=STATUS_POLICY_REJECTED,
                target_name=target.name,
                source_head=source_head,
                changed_paths=actual,
                validator_checks=checks,
                validator_runs=(),
                message=(
                    "Post-apply changed-path set "
                    "does not match preflight set"
                ),
            )

        post_rejected = _policy_rejections(
            policy,
            actual,
        )

        if post_rejected:
            return CandidateEvaluation(
                status=STATUS_POLICY_REJECTED,
                target_name=target.name,
                source_head=source_head,
                changed_paths=actual,
                validator_checks=checks,
                validator_runs=(),
                message=(
                    "Post-apply policy rejection: "
                    + ", ".join(
                        post_rejected
                    )
                ),
            )

        runs = run_validators(
            worktree.path,
            checks,
            timeout=timeout,
        )

        failed = tuple(
            run
            for run in runs
            if not run.passed
        )

        if failed:
            detail = "; ".join(
                (
                    f"{run.name}: timeout"
                    if run.timed_out
                    else (
                        f"{run.name}: "
                        f"exit={run.returncode}"
                    )
                )
                for run in failed
            )

            return CandidateEvaluation(
                status=STATUS_VALIDATION_FAILED,
                target_name=target.name,
                source_head=source_head,
                changed_paths=actual,
                validator_checks=checks,
                validator_runs=runs,
                message=detail,
            )

        if _on_validated_worktree is not None:
            _on_validated_worktree(worktree.path)

        return CandidateEvaluation(
            status=STATUS_PASS,
            target_name=target.name,
            source_head=source_head,
            changed_paths=actual,
            validator_checks=checks,
            validator_runs=runs,
            message=(
                "Candidate passed policy and "
                "all verified validators"
            ),
        )

    except Exception as error:
        return CandidateEvaluation(
            status=STATUS_INTERNAL_ERROR,
            target_name=target.name,
            source_head=source_head,
            changed_paths=(),
            validator_checks=(),
            validator_runs=(),
            message=(
                f"{type(error).__name__}: {error}"
            ),
        )

    finally:
        if worktree is not None:
            abandon_target_worktree(
                worktree
            )

        if (
            patch_file is not None
            and patch_file.exists()
        ):
            patch_file.unlink()

        final_head = target_head(target)

        if final_head != source_head:
            raise RuntimeError(
                "CRITICAL: target HEAD changed "
                "during V2C evaluation"
            )

def _evaluate_candidate_patch_from_snapshot(
    target: TargetSpec,
    baseline_patch: str | bytes,
    candidate_patch: str | bytes,
    *,
    timeout: int = DEFAULT_VALIDATION_TIMEOUT,
    _on_validated_worktree: Callable[[Path], None] | None = None,
) -> CandidateEvaluation:
    """Evaluate a candidate relative to an explicit dirty-state overlay.

    Both overlays are applied only inside one detached disposable
    worktree. The target worktree, index, files and HEAD are never
    mutated.
    """

    source_head = target_head(target)
    source_status = _git(
        target.repo,
        "status",
        "--porcelain=v1",
        "-z",
    ).stdout

    policy = build_target_policy(target)

    try:
        baseline_payload = (
            baseline_patch.encode("utf-8")
            if isinstance(baseline_patch, str)
            else bytes(baseline_patch)
        )
        candidate_payload = (
            candidate_patch.encode("utf-8")
            if isinstance(candidate_patch, str)
            else bytes(candidate_patch)
        )
    except Exception as error:
        return CandidateEvaluation(
            status=STATUS_PATCH_INVALID,
            target_name=target.name,
            source_head=source_head,
            changed_paths=(),
            validator_checks=(),
            validator_runs=(),
            message=f"Invalid patch payload: {error}",
        )

    baseline_file: Path | None = None
    candidate_file: Path | None = None
    worktree = None
    candidate_paths: tuple[str, ...] = ()

    def result(
        status: str,
        message: str,
        *,
        checks: tuple[ValidatorCheck, ...] = (),
        runs: tuple[ValidatorRun, ...] = (),
    ) -> CandidateEvaluation:
        return CandidateEvaluation(
            status=status,
            target_name=target.name,
            source_head=source_head,
            changed_paths=candidate_paths,
            validator_checks=checks,
            validator_runs=runs,
            message=message,
        )

    try:
        with tempfile.NamedTemporaryFile(
            prefix="sophyane-baseline-",
            suffix=".patch",
            delete=False,
        ) as handle:
            handle.write(baseline_payload)
            baseline_file = Path(handle.name)

        with tempfile.NamedTemporaryFile(
            prefix="sophyane-candidate-",
            suffix=".patch",
            delete=False,
        ) as handle:
            handle.write(candidate_payload)
            candidate_file = Path(handle.name)

        try:
            baseline_paths = _patch_paths(
                target.repo,
                baseline_file,
            )
        except (UnicodeDecodeError, ValueError) as error:
            return result(
                STATUS_PATCH_INVALID,
                f"Baseline patch rejected: {error}",
            )

        try:
            candidate_paths = _patch_paths(
                target.repo,
                candidate_file,
            )
        except (UnicodeDecodeError, ValueError) as error:
            return result(
                STATUS_PATCH_INVALID,
                f"Candidate patch rejected: {error}",
            )

        rejected = _policy_rejections(
            policy,
            candidate_paths,
        )

        if rejected:
            return result(
                STATUS_POLICY_REJECTED,
                "Candidate patch touches non-mutable paths: "
                + ", ".join(rejected),
            )

        worktree = create_target_worktree(target)

        if target_head(target) != source_head:
            raise RuntimeError(
                "Target HEAD changed while snapshot "
                "evaluation was starting"
            )

        baseline_check = _git(
            worktree.path,
            "apply",
            "--check",
            str(baseline_file),
            check=False,
        )

        if baseline_check.returncode != 0:
            message = baseline_check.stderr.decode(
                "utf-8",
                errors="replace",
            ).strip()
            return result(
                STATUS_PATCH_INVALID,
                "Baseline patch does not apply: " + message,
            )

        baseline_apply = _git(
            worktree.path,
            "apply",
            str(baseline_file),
            check=False,
        )

        if baseline_apply.returncode != 0:
            message = baseline_apply.stderr.decode(
                "utf-8",
                errors="replace",
            ).strip()
            return result(
                STATUS_PATCH_INVALID,
                "Baseline patch application failed: "
                + message,
            )

        baseline_actual = _actual_changed_paths(
            worktree.path
        )

        if set(baseline_actual) != set(baseline_paths):
            return result(
                STATUS_PATCH_INVALID,
                "Baseline changed-path set does not "
                "match preflight",
            )

        candidate_check = _git(
            worktree.path,
            "apply",
            "--check",
            str(candidate_file),
            check=False,
        )

        if candidate_check.returncode != 0:
            message = candidate_check.stderr.decode(
                "utf-8",
                errors="replace",
            ).strip()
            return result(
                STATUS_PATCH_INVALID,
                "Candidate patch does not apply to "
                "baseline: " + message,
            )

        candidate_apply = _git(
            worktree.path,
            "apply",
            str(candidate_file),
            check=False,
        )

        if candidate_apply.returncode != 0:
            message = candidate_apply.stderr.decode(
                "utf-8",
                errors="replace",
            ).strip()
            return result(
                STATUS_PATCH_INVALID,
                "Candidate patch application failed: "
                + message,
            )

        final_actual = _actual_changed_paths(
            worktree.path
        )
        expected = set(baseline_paths) | set(
            candidate_paths
        )

        if set(final_actual) != expected:
            return result(
                STATUS_POLICY_REJECTED,
                "Final changed-path set does not match "
                "baseline and candidate preflight",
            )

        post_rejected = _policy_rejections(
            policy,
            candidate_paths,
        )

        if post_rejected:
            return result(
                STATUS_POLICY_REJECTED,
                "Post-apply candidate policy rejection: "
                + ", ".join(post_rejected),
            )

        checks = verify_validators(
            worktree.path,
            policy.validators,
        )

        if not checks:
            return result(
                STATUS_VALIDATION_UNAVAILABLE,
                "No validators discovered for target",
            )

        unavailable = tuple(
            check
            for check in checks
            if not check.runnable
        )

        if unavailable:
            detail = "; ".join(
                f"{check.spec.name}: {check.reason}"
                for check in unavailable
            )
            return result(
                STATUS_VALIDATION_UNAVAILABLE,
                "Not all discovered validators are "
                "runnable: " + detail,
                checks=checks,
            )

        runs = run_validators(
            worktree.path,
            checks,
            timeout=timeout,
        )

        failed = tuple(
            run
            for run in runs
            if not run.passed
        )

        if failed:
            detail = "; ".join(
                (
                    f"{run.name}: timeout"
                    if run.timed_out
                    else f"{run.name}: exit={run.returncode}"
                )
                for run in failed
            )
            return result(
                STATUS_VALIDATION_FAILED,
                detail,
                checks=checks,
                runs=runs,
            )

        if _on_validated_worktree is not None:
            _on_validated_worktree(worktree.path)

        return result(
            STATUS_PASS,
            "Candidate passed snapshot policy and "
            "all verified validators",
            checks=checks,
            runs=runs,
        )

    except Exception as error:
        return result(
            STATUS_INTERNAL_ERROR,
            f"{type(error).__name__}: {error}",
        )

    finally:
        if worktree is not None:
            abandon_target_worktree(worktree)

        for patch_file in (
            baseline_file,
            candidate_file,
        ):
            if (
                patch_file is not None
                and patch_file.exists()
            ):
                patch_file.unlink()

        final_head = target_head(target)
        final_status = _git(
            target.repo,
            "status",
            "--porcelain=v1",
            "-z",
        ).stdout

        if final_head != source_head:
            raise RuntimeError(
                "CRITICAL: target HEAD changed during "
                "snapshot evaluation"
            )

        if final_status != source_status:
            raise RuntimeError(
                "CRITICAL: target status changed during "
                "snapshot evaluation"
            )

def evaluate_candidate_patch_from_snapshot(
    target: TargetSpec,
    baseline_patch: str | bytes,
    candidate_patch: str | bytes,
    *,
    timeout: int = DEFAULT_VALIDATION_TIMEOUT,
) -> CandidateEvaluation:
    """Evaluate a candidate relative to an explicit baseline overlay."""

    return _evaluate_candidate_patch_from_snapshot(
        target,
        baseline_patch,
        candidate_patch,
        timeout=timeout,
    )


def _validated_challenge_requests(
    requests: Iterable[ChallengeRequest],
) -> tuple[ChallengeRequest, ...]:
    if isinstance(requests, (str, bytes)):
        raise ValueError(
            "requests must be an iterable of ChallengeRequest"
        )

    try:
        items = tuple(requests)
    except (TypeError, RuntimeError) as error:
        raise ValueError(
            "requests must be iterable"
        ) from error

    if any(
        not isinstance(item, ChallengeRequest)
        for item in items
    ):
        raise ValueError(
            "every request must be a ChallengeRequest"
        )

    identifiers = tuple(
        item.challenge_id
        for item in items
    )

    if len(set(identifiers)) != len(identifiers):
        raise ValueError(
            "duplicate challenge_id values are not allowed"
        )

    return items


def evaluate_candidate_patch_from_snapshot_with_trusted_challenges(
    target: TargetSpec,
    baseline_patch: str | bytes,
    candidate_patch: str | bytes,
    requests: Iterable[ChallengeRequest],
    *,
    timeout: int = DEFAULT_VALIDATION_TIMEOUT,
) -> TrustedCandidateEvaluation:
    """Evaluate ordinary and trusted gates in one disposable worktree."""

    items = _validated_challenge_requests(
        requests
    )
    supplemental: list[
        TrustedSupplementalResult
    ] = []

    def execute_trusted(
        worktree: Path,
    ) -> None:
        supplemental.append(
            run_trusted_supplemental_challenges(
                worktree,
                items,
                timeout=timeout,
            )
        )

    candidate = _evaluate_candidate_patch_from_snapshot(
        target,
        baseline_patch,
        candidate_patch,
        timeout=timeout,
        _on_validated_worktree=execute_trusted,
    )

    trusted = (
        supplemental[0]
        if candidate.passed and supplemental
        else None
    )

    return TrustedCandidateEvaluation(
        candidate=candidate,
        supplemental=trusted,
    )

def evaluate_candidate_patch(
    target: TargetSpec,
    patch: str | bytes,
    *,
    timeout: int = DEFAULT_VALIDATION_TIMEOUT,
) -> CandidateEvaluation:
    """Evaluate a unified Git patch without mutating target HEAD."""

    return _evaluate_candidate_patch(
        target,
        patch,
        timeout=timeout,
    )


def evaluate_candidate_patch_with_trusted_challenges(
    target: TargetSpec,
    patch: str | bytes,
    requests: Iterable[ChallengeRequest],
    *,
    timeout: int = DEFAULT_VALIDATION_TIMEOUT,
) -> TrustedCandidateEvaluation:
    """Evaluate ordinary and trusted gates in one clean worktree."""

    items = _validated_challenge_requests(
        requests
    )
    supplemental: list[
        TrustedSupplementalResult
    ] = []

    def execute_trusted(
        worktree: Path,
    ) -> None:
        supplemental.append(
            run_trusted_supplemental_challenges(
                worktree,
                items,
                timeout=timeout,
            )
        )

    candidate = _evaluate_candidate_patch(
        target,
        patch,
        timeout=timeout,
        _on_validated_worktree=execute_trusted,
    )

    trusted = (
        supplemental[0]
        if candidate.passed and supplemental
        else None
    )

    return TrustedCandidateEvaluation(
        candidate=candidate,
        supplemental=trusted,
    )
