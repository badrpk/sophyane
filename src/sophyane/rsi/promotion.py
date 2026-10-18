"""Isolated live-branch promotion for verified native RSI candidates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import subprocess
import sys
import time

from sophyane.rsi_host_broker import PromotionResult, promote


@dataclass(frozen=True)
class LivePromotionResult:
    promoted: bool
    active_commit: str
    checkpoint_commit: str
    reason: str = ""
    health_exit_code: int | None = None


class PromotionManager:
    """Promote a verified commit without touching the user's checkout."""

    def __init__(self, repo: str | Path, state_dir: str | Path, *, branch: str = "sophyane-rsi-live", health_command: tuple[str, ...] | None = None) -> None:
        self.repo = Path(repo).resolve()
        self.state_dir = Path(state_dir).resolve()
        self.branch = branch
        self.live_worktree = self.state_dir / "live-worktree"
        self.health_command = health_command or (sys.executable, "-c", "import sophyane")
        self.ledger = self.state_dir / "promotion.events.jsonl"

    def _git(self, *args: str, cwd: Path | None = None) -> str:
        result = subprocess.run(["git", *args], cwd=cwd or self.repo, check=True, capture_output=True, text=True)
        return result.stdout.strip()

    def _commit_exists(self, commit: str) -> bool:
        try:
            return self._git("rev-parse", "--verify", f"{commit}^{{commit}}") == commit
        except subprocess.CalledProcessError:
            return False

    def _branch_commit(self) -> str | None:
        try:
            return self._git("rev-parse", "--verify", self.branch)
        except subprocess.CalledProcessError:
            return None

    def _ensure_live_worktree(self, base: str) -> str:
        current = self._branch_commit()
        if current is None:
            self._git("branch", self.branch, base)
            current = base
        if not self.live_worktree.exists():
            self.state_dir.mkdir(parents=True, exist_ok=True)
            self._git("worktree", "add", str(self.live_worktree), self.branch)
        return current

    def _record(self, event: str, result: LivePromotionResult) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        payload = {"event": event, "recorded_at": time.time(), **asdict(result)}
        with self.ledger.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, sort_keys=True) + "\n")
        (self.state_dir / "promotion.json").write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

    def _reset_live(self, commit: str) -> None:
        self._git("reset", "--hard", commit, cwd=self.live_worktree)
        self._git("update-ref", self.branch, commit)

    def promote(self, candidate_commit: str, *, expected_base: str) -> LivePromotionResult:
        candidate_commit = str(candidate_commit).strip()
        expected_base = str(expected_base).strip()
        if not candidate_commit or not expected_base or not self._commit_exists(candidate_commit):
            return LivePromotionResult(False, self._branch_commit() or "", expected_base, "candidate commit unavailable")
        active = self._ensure_live_worktree(expected_base)
        if active != expected_base:
            result = LivePromotionResult(False, active, expected_base, "live branch diverged from expected base")
            self._record("promotion_refused", result)
            return result
        try:
            self._git("merge-base", "--is-ancestor", expected_base, candidate_commit)
        except subprocess.CalledProcessError:
            result = LivePromotionResult(False, active, expected_base, "candidate is not based on expected base")
            self._record("promotion_refused", result)
            return result
        self._git("merge", "--ff-only", candidate_commit, cwd=self.live_worktree)
        health = subprocess.run(list(self.health_command), cwd=self.live_worktree, capture_output=True, text=True, check=False)
        if health.returncode != 0:
            self._reset_live(expected_base)
            result = LivePromotionResult(False, expected_base, expected_base, "live health check failed; rolled back", health.returncode)
            self._record("promotion_rolled_back", result)
            return result
        result = LivePromotionResult(True, candidate_commit, expected_base, "live health check passed", 0)
        self._record("promotion_verified", result)
        return result

    def rollback(self) -> PromotionResult:
        payload = {}
        state = self.state_dir / "promotion.json"
        if state.is_file():
            payload = json.loads(state.read_text(encoding="utf-8"))
        checkpoint = str(payload.get("checkpoint_commit") or "")
        recorded_active = str(payload.get("active_commit") or "")
        active = self._branch_commit() or ""
        if not checkpoint:
            result = LivePromotionResult(False, active, "", "no recorded promotion checkpoint")
            self._record("rollback_refused", result)
            return result
        if active not in {checkpoint, recorded_active}:
            result = LivePromotionResult(False, active, checkpoint, "rollback refused: live branch diverged")
            self._record("rollback_refused", result)
            return result
        if active != checkpoint:
            self._reset_live(checkpoint)
        result = LivePromotionResult(True, checkpoint, checkpoint, "rollback complete", 0)
        self._record("rollback_complete", result)
        return result


__all__ = ["PromotionManager", "LivePromotionResult", "PromotionResult", "promote"]
