from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from sophyane.rsi.promotion import PromotionManager


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def make_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    (repo / "value.txt").write_text("base\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-b", "candidate")
    (repo / "value.txt").write_text("improved\n")
    git(repo, "commit", "-am", "candidate")
    candidate = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "main")
    return repo, base, candidate


def test_promotion_fast_forwards_isolated_live_branch(tmp_path: Path):
    repo, base, candidate = make_repo(tmp_path)
    manager = PromotionManager(
        repo,
        tmp_path / "state",
        health_command=(sys.executable, "-c", "raise SystemExit(0)"),
    )

    result = manager.promote(candidate, expected_base=base)

    assert result.promoted is True
    assert result.checkpoint_commit == base
    assert result.active_commit == candidate
    assert git(repo, "rev-parse", "sophyane-rsi-live") == candidate


def test_promotion_refuses_live_branch_divergence(tmp_path: Path):
    repo, base, candidate = make_repo(tmp_path)
    manager = PromotionManager(
        repo,
        tmp_path / "state",
        health_command=(sys.executable, "-c", "raise SystemExit(0)"),
    )
    assert manager.promote(candidate, expected_base=base).promoted

    (repo / "value.txt").write_text("unrelated\n")
    git(repo, "commit", "-am", "unrelated-main")
    newer = git(repo, "rev-parse", "HEAD")

    result = manager.promote(newer, expected_base=base)

    assert result.promoted is False
    assert "diverged" in result.reason


def test_failed_health_check_rolls_back_to_checkpoint(tmp_path: Path):
    repo, base, candidate = make_repo(tmp_path)
    manager = PromotionManager(
        repo,
        tmp_path / "state",
        health_command=(sys.executable, "-c", "raise SystemExit(7)"),
    )

    result = manager.promote(candidate, expected_base=base)

    assert result.promoted is False
    assert result.active_commit == base
    assert git(repo, "rev-parse", "sophyane-rsi-live") == base


def test_rollback_is_idempotent(tmp_path: Path):
    repo, base, candidate = make_repo(tmp_path)
    manager = PromotionManager(
        repo,
        tmp_path / "state",
        health_command=(sys.executable, "-c", "raise SystemExit(0)"),
    )
    assert manager.promote(candidate, expected_base=base).promoted

    first = manager.rollback()
    second = manager.rollback()

    assert first.active_commit == base
    assert second.active_commit == base
    assert git(repo, "rev-parse", "sophyane-rsi-live") == base


def test_rollback_refuses_unrelated_live_commit(tmp_path: Path):
    repo, base, candidate = make_repo(tmp_path)
    manager = PromotionManager(
        repo,
        tmp_path / "state",
        health_command=(sys.executable, "-c", "raise SystemExit(0)"),
    )
    assert manager.promote(candidate, expected_base=base).promoted
    live = tmp_path / "state" / "live-worktree"
    (live / "value.txt").write_text("unrelated-live\n")
    git(live, "commit", "-am", "unrelated-live")

    result = manager.rollback()

    assert result.promoted is False
    assert "diverged" in result.reason
