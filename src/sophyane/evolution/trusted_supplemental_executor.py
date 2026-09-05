"""Evidence-only execution of trusted supplemental challenges."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .red_queen_policy import ChallengeRequest
from .target_validation import DEFAULT_VALIDATION_TIMEOUT

__all__ = [
    "TrustedSupplementalEvidence",
    "TrustedSupplementalResult",
    "TrustedSupplementalExecutionError",
    "run_trusted_supplemental_challenges",
]

_TESTS = {
    "targeted": "tests/red_queen/test_targeted_supplemental.py",
    "regression": "tests/red_queen/test_regression_supplemental.py",
    "security": "tests/red_queen/test_security_supplemental.py",
    "held_out": "tests/red_queen/test_held_out_supplemental.py",
}
_OUTPUT_LIMIT = 8192


class TrustedSupplementalExecutionError(RuntimeError):
    """The supplied worktree or challenge collection is unsafe."""


@dataclass(frozen=True)
class TrustedSupplementalEvidence:
    family: str
    challenge_id: str
    evaluator_identity: str
    test_path: str
    executed: bool
    passed: bool
    returncode: int | None
    timed_out: bool
    elapsed_seconds: float
    stdout: str
    stderr: str
    rejection_reason: str | None


@dataclass(frozen=True)
class TrustedSupplementalResult:
    status: str
    evidence: tuple[TrustedSupplementalEvidence, ...]

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


def _run_git(worktree: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ("git", "-C", str(worktree), *args),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _snapshot(worktree: Path) -> tuple[bytes, bytes]:
    head = _run_git(worktree, "rev-parse", "HEAD")
    status = _run_git(worktree, "status", "--porcelain=v1", "-z")
    if head.returncode or status.returncode:
        raise TrustedSupplementalExecutionError("unable to snapshot worktree")
    return head.stdout.strip(), status.stdout


def _validated_worktree(value: str | os.PathLike[str]) -> Path:
    supplied = Path(value)
    if supplied.is_symlink() or not supplied.is_dir():
        raise TrustedSupplementalExecutionError("worktree must be a real directory")
    worktree = supplied.resolve()
    inside = _run_git(worktree, "rev-parse", "--is-inside-work-tree")
    if inside.returncode or inside.stdout.strip() != b"true":
        raise TrustedSupplementalExecutionError("path is not a Git worktree")
    attached = _run_git(worktree, "symbolic-ref", "-q", "HEAD")
    if attached.returncode == 0:
        raise TrustedSupplementalExecutionError("worktree HEAD must be detached")
    _snapshot(worktree)
    return worktree


def _bounded(value: bytes | str | None) -> str:
    if value is None:
        return ""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    return text[:_OUTPUT_LIMIT]


def _evidence(
    request: ChallengeRequest,
    path: str,
    *,
    executed: bool = False,
    passed: bool = False,
    returncode: int | None = None,
    timed_out: bool = False,
    elapsed: float = 0.0,
    stdout: bytes | str | None = None,
    stderr: bytes | str | None = None,
    rejection: str | None = None,
) -> TrustedSupplementalEvidence:
    return TrustedSupplementalEvidence(
        family=request.family,
        challenge_id=request.challenge_id,
        evaluator_identity=request.evaluator_identity,
        test_path=path,
        executed=executed,
        passed=passed,
        returncode=returncode,
        timed_out=timed_out,
        elapsed_seconds=max(0.0, elapsed),
        stdout=_bounded(stdout),
        stderr=_bounded(stderr),
        rejection_reason=rejection,
    )


def _trusted_test(worktree: Path, relative: str) -> tuple[Path | None, str | None]:
    candidate = worktree / relative
    if candidate.is_symlink():
        return None, "supplemental test must not be a symlink"
    if not candidate.exists():
        return None, "supplemental test is missing"
    if not candidate.is_file():
        return None, "supplemental test is not a regular file"
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(worktree)
    except (OSError, ValueError):
        return None, "supplemental test escapes the worktree"
    expected = worktree.joinpath(*Path(relative).parts)
    if resolved != expected:
        return None, "supplemental test resolved to a different path"
    return resolved, None


def _execute_test(
    worktree: Path,
    request: ChallengeRequest,
    relative: str,
    timeout: float,
) -> TrustedSupplementalEvidence:
    trusted, rejection = _trusted_test(worktree, relative)
    if rejection:
        return _evidence(request, relative, rejection=rejection)
    started = time.monotonic()
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    command = (sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", relative)
    try:
        completed = subprocess.run(
            command,
            cwd=worktree,
            env=env,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return _evidence(
            request,
            relative,
            executed=True,
            timed_out=True,
            elapsed=time.monotonic() - started,
            stdout=exc.stdout,
            stderr=exc.stderr,
            rejection="supplemental test timed out",
        )
    return _evidence(
        request,
        relative,
        executed=True,
        passed=completed.returncode == 0,
        returncode=completed.returncode,
        elapsed=time.monotonic() - started,
        stdout=completed.stdout,
        stderr=completed.stderr,
        rejection=None if completed.returncode == 0 else "supplemental test failed",
    )


def _invalidated(item: TrustedSupplementalEvidence) -> TrustedSupplementalEvidence:
    return TrustedSupplementalEvidence(
        family=item.family,
        challenge_id=item.challenge_id,
        evaluator_identity=item.evaluator_identity,
        test_path=item.test_path,
        executed=item.executed,
        passed=False,
        returncode=item.returncode,
        timed_out=item.timed_out,
        elapsed_seconds=item.elapsed_seconds,
        stdout=item.stdout,
        stderr=item.stderr,
        rejection_reason="worktree HEAD or status changed during challenge",
    )


def run_trusted_supplemental_challenges(
    worktree: str | os.PathLike[str],
    requests: Iterable[ChallengeRequest],
    *,
    timeout: float = DEFAULT_VALIDATION_TIMEOUT,
) -> TrustedSupplementalResult:
    """Run fixed supplemental tests in a caller-owned detached worktree."""
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise TrustedSupplementalExecutionError("timeout must be positive")
    try:
        items = tuple(requests)
    except (TypeError, RuntimeError) as exc:
        raise TrustedSupplementalExecutionError("requests must be iterable") from exc
    if any(not isinstance(item, ChallengeRequest) for item in items):
        raise TrustedSupplementalExecutionError("every request must be a ChallengeRequest")
    identifiers = [item.challenge_id for item in items]
    if len(set(identifiers)) != len(identifiers):
        raise TrustedSupplementalExecutionError("duplicate challenge_id")

    root = _validated_worktree(worktree)
    original = _snapshot(root)
    evidence: list[TrustedSupplementalEvidence] = []
    for request in items:
        relative = _TESTS.get(request.family)
        if relative is None:
            item = _evidence(request, "", rejection="unsupported challenge family")
        else:
            item = _execute_test(root, request, relative, float(timeout))
        try:
            current = _snapshot(root)
        except TrustedSupplementalExecutionError:
            evidence.append(_invalidated(item))
            return TrustedSupplementalResult("INVALID", tuple(evidence))
        if current != original:
            evidence.append(_invalidated(item))
            return TrustedSupplementalResult("INVALID", tuple(evidence))
        evidence.append(item)

    passed = bool(evidence) and all(item.executed and item.passed for item in evidence)
    return TrustedSupplementalResult("PASS" if passed else "FAIL", tuple(evidence))
