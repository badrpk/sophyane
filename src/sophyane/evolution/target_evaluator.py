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


def evaluate_candidate_patch(
    target: TargetSpec,
    patch: str | bytes,
    *,
    timeout: int = DEFAULT_VALIDATION_TIMEOUT,
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
