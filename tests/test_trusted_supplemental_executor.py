from __future__ import annotations

import inspect
import os
import subprocess
from pathlib import Path

import pytest

from sophyane.evolution.red_queen_policy import ChallengeRequest
from sophyane.evolution.trusted_supplemental_executor import (
    TrustedSupplementalExecutionError,
    run_trusted_supplemental_challenges,
)

PATHS = {
    "targeted": "tests/red_queen/test_targeted_supplemental.py",
    "regression": "tests/red_queen/test_regression_supplemental.py",
    "security": "tests/red_queen/test_security_supplemental.py",
    "held_out": "tests/red_queen/test_held_out_supplemental.py",
}


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ("git", "-C", str(repo), *args),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def challenge(family: str, suffix: str = "x") -> ChallengeRequest:
    return ChallengeRequest(family, f"{family}-{suffix}", 1, "fixture")


def detached_repo(tmp_path: Path, sources: dict[str, str] | None = None) -> tuple[Path, Path]:
    source = tmp_path / "source"
    worktree = tmp_path / "worktree"
    source.mkdir()
    git(source, "init")
    git(source, "config", "user.email", "test@example.invalid")
    git(source, "config", "user.name", "Test")
    (source / "authoritative.txt").write_text("stable\n")
    for relative, body in (sources or {path: "def test_ok(): assert True\n" for path in PATHS.values()}).items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    git(source, "add", ".")
    git(source, "commit", "-m", "fixture")
    git(source, "worktree", "add", "--detach", str(worktree), "HEAD")
    return source, worktree


def state(repo: Path) -> tuple[bytes, bytes, bytes]:
    return (
        git(repo, "rev-parse", "HEAD"),
        git(repo, "status", "--porcelain=v1", "-z"),
        (repo / "authoritative.txt").read_bytes(),
    )


def test_all_families_use_exact_fixed_paths_and_pass(tmp_path: Path) -> None:
    _, worktree = detached_repo(tmp_path)
    requests = [challenge(family) for family in PATHS]
    result = run_trusted_supplemental_challenges(worktree, requests, timeout=20)
    assert result.status == "PASS"
    assert [item.test_path for item in result.evidence] == list(PATHS.values())
    assert all(item.executed and item.passed for item in result.evidence)


def test_failure_has_executed_evidence(tmp_path: Path) -> None:
    _, worktree = detached_repo(tmp_path, {PATHS["targeted"]: "def test_no(): assert False\n"})
    result = run_trusted_supplemental_challenges(worktree, [challenge("targeted")], timeout=20)
    item = result.evidence[0]
    assert result.status == "FAIL"
    assert item.executed and not item.passed and item.returncode != 0


def test_missing_test_fails_without_execution(tmp_path: Path) -> None:
    _, worktree = detached_repo(tmp_path)
    (worktree / PATHS["targeted"]).unlink()
    result = run_trusted_supplemental_challenges(worktree, [challenge("targeted")], timeout=20)
    item = result.evidence[0]
    assert result.status == "FAIL"
    assert not item.executed and not item.passed
    assert item.rejection_reason == "supplemental test is missing"


def test_duplicate_ids_rejected_before_execution(tmp_path: Path) -> None:
    body = "from pathlib import Path\ndef test_run(): Path('ran').write_text('yes')\n"
    _, worktree = detached_repo(tmp_path, {PATHS["targeted"]: body})
    first = challenge("targeted", "same")
    second = ChallengeRequest("regression", first.challenge_id, 1, "fixture")
    with pytest.raises(TrustedSupplementalExecutionError, match="duplicate"):
        run_trusted_supplemental_challenges(worktree, [first, second], timeout=20)
    assert not (worktree / "ran").exists()


def test_symlinked_test_is_rejected(tmp_path: Path) -> None:
    _, worktree = detached_repo(tmp_path)
    test_path = worktree / PATHS["security"]
    test_path.unlink()
    os.symlink(worktree / "authoritative.txt", test_path)
    result = run_trusted_supplemental_challenges(worktree, [challenge("security")], timeout=20)
    item = result.evidence[0]
    assert result.status == "FAIL"
    assert not item.executed
    assert "symlink" in (item.rejection_reason or "")


def test_timeout_is_executed_failure(tmp_path: Path) -> None:
    body = "import time\ndef test_slow(): time.sleep(2)\n"
    _, worktree = detached_repo(tmp_path, {PATHS["held_out"]: body})
    result = run_trusted_supplemental_challenges(worktree, [challenge("held_out")], timeout=.05)
    item = result.evidence[0]
    assert result.status == "FAIL"
    assert item.executed and item.timed_out and not item.passed
    assert item.returncode is None


def test_status_change_makes_result_invalid(tmp_path: Path) -> None:
    body = "from pathlib import Path\ndef test_dirty(): Path('dirty.txt').write_text('x')\n"
    _, worktree = detached_repo(tmp_path, {PATHS["regression"]: body})
    result = run_trusted_supplemental_challenges(worktree, [challenge("regression")], timeout=20)
    assert result.status == "INVALID"
    assert result.evidence[0].executed
    assert not result.evidence[0].passed
    assert "status changed" in (result.evidence[0].rejection_reason or "")


def test_public_signature_has_no_command_or_test_path() -> None:
    signature = inspect.signature(run_trusted_supplemental_challenges)
    assert list(signature.parameters) == ["worktree", "requests", "timeout"]
    assert signature.parameters["timeout"].kind is inspect.Parameter.KEYWORD_ONLY


def test_authoritative_repository_remains_unchanged(tmp_path: Path) -> None:
    source, worktree = detached_repo(tmp_path)
    before = state(source)
    result = run_trusted_supplemental_challenges(
        worktree, [challenge("targeted")], timeout=20
    )
    assert result.status == "PASS"
    assert state(source) == before


def test_empty_collection_cannot_pass(tmp_path: Path) -> None:
    _, worktree = detached_repo(tmp_path)
    result = run_trusted_supplemental_challenges(worktree, [], timeout=20)
    assert result.status == "FAIL"
    assert result.evidence == ()


def test_attached_repository_is_rejected(tmp_path: Path) -> None:
    source, _ = detached_repo(tmp_path)
    with pytest.raises(TrustedSupplementalExecutionError, match="detached"):
        run_trusted_supplemental_challenges(
            source, [challenge("targeted")], timeout=20
        )


def test_non_challenge_and_duplicate_validation_precede_worktree_check(tmp_path: Path) -> None:
    missing = tmp_path / "not-a-worktree"
    with pytest.raises(TrustedSupplementalExecutionError, match="every request"):
        run_trusted_supplemental_challenges(missing, [object()], timeout=20)
    same = challenge("targeted", "same")
    duplicate = ChallengeRequest("security", same.challenge_id, 1, "fixture")
    with pytest.raises(TrustedSupplementalExecutionError, match="duplicate"):
        run_trusted_supplemental_challenges(missing, [same, duplicate], timeout=20)


def test_module_has_no_mutating_git_or_lifecycle_route() -> None:
    import sophyane.evolution.trusted_supplemental_executor as module

    source = inspect.getsource(module)
    forbidden = (
        '"worktree", "add"',
        '"apply"',
        '"commit"',
        '"branch"',
        '"stash"',
        '"reset"',
        '"clean"',
        "promote",
        "abandon_target_worktree",
        "create_target_worktree",
    )
    assert all(token not in source for token in forbidden)
