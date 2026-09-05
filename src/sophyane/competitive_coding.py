"""Fail-closed Phase-1 competitive coding coordinator."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from sophyane.global_txq import (
    GlobalTxqPolicy,
    choose_global_txq_policy,
)

__all__ = [
    "CompetitiveCandidateResult",
    "CompetitiveCodingResult",
    "CompetitiveCodingError",
    "run_competitive_coding",
    "request_competitive_application",
    "apply_competitive_application",
]


MISSING_BOUNDARY = (
    "objective_driven_multi_worktree_gate_coordinator"
)


class CompetitiveCodingError(RuntimeError):
    """Raised when Phase-1 input cannot be handled safely."""


@dataclass(frozen=True)
class CompetitiveCandidateResult:
    candidate_id: str
    valid: bool
    patch: str
    rejection_reason: str


@dataclass(frozen=True)
class CompetitiveCodingResult:
    objective: str
    repository: Path
    txq_policy: GlobalTxqPolicy
    candidates: tuple[CompetitiveCandidateResult, ...]
    status: str
    missing_boundary: str
    winner: None = None


def _require_git_repository(repository: Path) -> Path:
    resolved = Path(repository).expanduser().resolve()

    if not resolved.is_dir():
        raise CompetitiveCodingError(
            "repository must be an existing directory"
        )

    result = subprocess.run(
        [
            "git",
            "-C",
            str(resolved),
            "rev-parse",
            "--is-inside-work-tree",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if (
        result.returncode != 0
        or result.stdout.strip() != "true"
    ):
        raise CompetitiveCodingError(
            "repository must be an existing Git repository"
        )

    return resolved


def _response_text(response: object) -> str:
    if isinstance(response, str):
        return response

    text = getattr(response, "text", None)

    if isinstance(text, str):
        return text

    raise CompetitiveCodingError(
        "provider response must be text or expose .text"
    )


def _safe_diff_path(raw_path: str) -> bool:
    path = raw_path.strip().split("\t", 1)[0]

    if path == "/dev/null":
        return True

    if not path or "\\" in path:
        return False

    if path.startswith(("a/", "b/")):
        path = path[2:]

    pure = PurePosixPath(path)

    return bool(
        path
        and not pure.is_absolute()
        and ".." not in pure.parts
    )


def _validate_patch(patch: str) -> str:
    if not patch.strip():
        return "empty proposal"

    lines = patch.splitlines()

    required = {
        "diff --git": any(
            line.startswith("diff --git ")
            for line in lines
        ),
        "---": any(
            line.startswith("--- ")
            for line in lines
        ),
        "+++": any(
            line.startswith("+++ ")
            for line in lines
        ),
        "@@": any(
            line.startswith("@@ ")
            for line in lines
        ),
    }

    missing = [
        marker
        for marker, present in required.items()
        if not present
    ]

    if missing:
        return (
            "missing unified-diff marker(s): "
            + ", ".join(missing)
        )

    paths: list[str] = []

    for line in lines:
        if line.startswith("diff --git "):
            try:
                parts = shlex.split(line)
            except ValueError:
                return "invalid diff --git header"

            if len(parts) != 4:
                return "invalid diff --git header"

            paths.extend(parts[2:])

        elif line.startswith(("--- ", "+++ ")):
            paths.append(line[4:])

    if not paths or any(
        not _safe_diff_path(path)
        for path in paths
    ):
        return "unsafe absolute or parent-traversal path"

    return ""


def _candidate_prompt(
    *,
    candidate_id: str,
    objective: str,
    repository: Path,
) -> str:
    return (
        f"Candidate ID: {candidate_id}\n"
        f"Objective: {objective}\n"
        f"Repository: {repository}\n"
        "Authority: read-only candidate proposer.\n"
        "Return one independent unified Git diff only. "
        "Do not modify files, commit, push, or install packages."
    )


def run_competitive_coding(
    *,
    objective: str,
    repository: Path,
    candidate_provider,
    candidate_count: int = 2,
    apply_winner: bool = False,
    progress: Callable[[str], None] | None = None,
) -> CompetitiveCodingResult:
    """Collect and validate proposals, then fail closed before mutation."""

    if not isinstance(objective, str) or not objective.strip():
        raise CompetitiveCodingError(
            "objective must be non-empty"
        )

    if (
        isinstance(candidate_count, bool)
        or not isinstance(candidate_count, int)
        or candidate_count < 2
    ):
        raise CompetitiveCodingError(
            "candidate_count must be at least two"
        )

    if not callable(candidate_provider):
        raise CompetitiveCodingError(
            "candidate_provider must be callable"
        )

    resolved = _require_git_repository(repository)
    normalized_objective = objective.strip()
    policy = choose_global_txq_policy(
        4,
        normalized_objective,
    )
    report = progress or (lambda _message: None)
    candidates: list[CompetitiveCandidateResult] = []

    for index in range(1, candidate_count + 1):
        candidate_id = f"candidate-{index}"
        report(f"Requesting {candidate_id}")

        try:
            response = candidate_provider(
                _candidate_prompt(
                    candidate_id=candidate_id,
                    objective=normalized_objective,
                    repository=resolved,
                )
            )
            patch = _response_text(response)
            rejection = _validate_patch(patch)
        except Exception as error:  # noqa: BLE001
            patch = ""
            rejection = (
                "provider failure: "
                f"{type(error).__name__}: {error}"
            )

        candidates.append(
            CompetitiveCandidateResult(
                candidate_id=candidate_id,
                valid=not rejection,
                patch=patch,
                rejection_reason=rejection,
            )
        )

    status = (
        "approval_required"
        if apply_winner
        else "fail_closed"
    )

    report(
        f"Competitive Phase 1 stopped: {MISSING_BOUNDARY}"
    )

    return CompetitiveCodingResult(
        objective=normalized_objective,
        repository=resolved,
        txq_policy=policy,
        candidates=tuple(candidates),
        status=status,
        missing_boundary=MISSING_BOUNDARY,
        winner=None,
    )

def request_competitive_application(evaluation):
    """Create the ranked-winner HITL request without applying anything."""
    from sophyane.competitive_coding_approval import request_competitive_approval
    return request_competitive_approval(evaluation)


def apply_competitive_application(
    evaluation, request_id: str, *, transaction_dir: Path | None = None,
    claim_ledger_dir: Path | None = None, application_dir: Path | None = None,
):
    """Apply only an explicitly approved evaluation through the hardened boundary."""
    from sophyane.competitive_coding_application import apply_competitive_application as _apply
    return _apply(evaluation, request_id, transaction_dir=transaction_dir, claim_ledger_dir=claim_ledger_dir, application_dir=application_dir)
