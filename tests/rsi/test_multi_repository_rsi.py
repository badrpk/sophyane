"""Repository ownership and durable promotion evidence across two Git checkouts."""

import json
from pathlib import Path
import subprocess
import sys

from sophyane.rsi.curriculum import CurriculumPolicy, CurriculumScheduler, CurriculumStore, CurriculumTask, TaskSource, TaskStatus
from sophyane.rsi.curriculum_runtime import ContinuousCurriculumRuntime
from sophyane.rsi.promotion import PromotionManager
from sophyane.rsi.runtime_services import build_curriculum_runtime


def git(path, *args):
    return subprocess.check_output(("git", "-C", str(path), *args), text=True).strip()


def repositories(tmp_path):
    root = tmp_path / "repos"
    root.mkdir()
    result = []
    for name in ("alpha", "beta"):
        repo = root / name
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.name", "Test")
        git(repo, "config", "user.email", "test@example.invalid")
        (repo / "src").mkdir()
        (repo / "src" / "value.py").write_text("VALUE = 1\n")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "base")
        git(repo, "remote", "add", "origin", f"https://github.com/badrpk/{name}.git")
        result.append(repo)
    return root, result


def task(name, base, *, task_id="improve", value="VALUE = 2\n"):
    return CurriculumTask(task_id, "seed", "improve value", ("src/value.py",), ("pytest",),
                          TaskSource.CURRICULUM, proposal_files={"src/value.py": value},
                          repository_id=f"badrpk/{name}", base_commit=base)


def manager(repo, state):
    return PromotionManager(repo, state, health_command=(sys.executable, "-c", "raise SystemExit(0)"))


def candidate(repo, value="VALUE = 2\n"):
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-qb", f"candidate-{value.encode().hex()}", base)
    (repo / "src" / "value.py").write_text(value)
    git(repo, "commit", "-qam", f"candidate-{repo.name}")
    commit = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    return base, commit


def test_inventory_context_round_robins_two_repositories(tmp_path, monkeypatch):
    root, _ = repositories(tmp_path)
    monkeypatch.setenv("SOPHYANE_REPOSITORY_ROOTS", str(root))
    monkeypatch.setenv("SOPHYANE_REPO_OWNER", "badrpk")
    monkeypatch.setenv("SOPHYANE_RSI_PROPOSAL_PROVIDER", "local_gguf")
    runtime = build_curriculum_runtime(tmp_path / "state", object(), proposal_adapter=object())
    first = runtime.context_factory()
    assert first.repository_id == "badrpk/alpha"
    assert first.base_commit == git(root / "alpha", "rev-parse", "HEAD")
    runtime.repository_inventory.complete_scan(first.repository)
    second = runtime.context_factory()
    assert second.repository_id == "badrpk/beta"
    assert second.repository.path == str((root / "beta").resolve())


def test_scoped_promotion_records_owner_task_and_candidate_without_touching_other_repo(tmp_path):
    _, (alpha, beta) = repositories(tmp_path)
    base, commit = candidate(alpha)
    beta_head = git(beta, "rev-parse", "HEAD")
    promotion = manager(alpha, tmp_path / "state" / "alpha")
    result = promotion.promote(commit, expected_base=base, task_id="improve", repository_id="badrpk/alpha",
                               reviewer="local_artifact:approve", isolation_result="qemu:passed",
                               post_promotion_checks=("health:passed",))
    record = json.loads((promotion.state_dir / "promotion.json").read_text())
    assert result.promoted
    assert {key: record[key] for key in ("task_id", "repository_id", "base_commit", "candidate_commit", "reviewer", "isolation_result")} == {
        "task_id": "improve", "repository_id": "badrpk/alpha", "base_commit": base,
        "candidate_commit": commit, "reviewer": "local_artifact:approve", "isolation_result": "qemu:passed"}
    assert record["post_promotion_checks"] == ["health:passed"]
    assert git(beta, "rev-parse", "HEAD") == beta_head
    assert (beta / "src" / "value.py").read_text() == "VALUE = 1\n"


def test_foreign_candidate_and_mismatched_identity_cannot_promote(tmp_path):
    _, (alpha, beta) = repositories(tmp_path)
    base, _ = candidate(alpha)
    _, foreign = candidate(beta)
    promotion = manager(alpha, tmp_path / "state" / "alpha")
    assert not promotion.promote(foreign, expected_base=base, task_id="x", repository_id="badrpk/alpha").promoted
    _, own = candidate(alpha, "VALUE = 3\n")
    assert not promotion.promote(own, expected_base=base, task_id="x", repository_id="badrpk/beta").promoted
    assert git(alpha, "rev-parse", "main") == base


def test_live_head_divergence_refuses_promotion(tmp_path):
    _, (alpha, _) = repositories(tmp_path)
    base, commit = candidate(alpha)
    promotion = manager(alpha, tmp_path / "state")
    assert promotion.promote(commit, expected_base=base, task_id="one", repository_id="badrpk/alpha").promoted
    live = promotion.live_worktree
    (live / "src" / "value.py").write_text("VALUE = 7\n")
    git(live, "commit", "-qam", "diverged")
    assert not promotion.promote(commit, expected_base=commit, task_id="two", repository_id="badrpk/alpha").promoted


def test_scoped_restart_requires_recorded_head_task_base_and_exact_bytes(tmp_path):
    _, (alpha, beta) = repositories(tmp_path)
    base, commit = candidate(alpha)
    promotion = manager(alpha, tmp_path / "state" / "alpha")
    assert promotion.promote(commit, expected_base=base, task_id="good", repository_id="badrpk/alpha").promoted
    store = CurriculumStore(promotion.state_dir / "curriculum.json")
    scheduler = CurriculumScheduler(store, CurriculumPolicy(cooldown_seconds=0))
    for item in (task("alpha", base, task_id="good"), task("alpha", base, task_id="other"),
                 task("beta", git(beta, "rev-parse", "HEAD"), task_id="foreign"),
                 task("alpha", "0" * 40, task_id="stale"),
                 task("alpha", base, task_id="bytes", value="VALUE = 9\n")):
        scheduler.enqueue(item)
    runtime = ContinuousCurriculumRuntime(promotion.state_dir, object(), scheduler, enabled=True)
    assert runtime.start()
    statuses = {item.task_id: item.status for item in store.load().queue}
    assert statuses["good"] is TaskStatus.VERIFIED
    assert all(statuses[item] is not TaskStatus.VERIFIED for item in ("other", "foreign", "stale", "bytes"))
    git(promotion.live_worktree, "reset", "--hard", base)
    restarted = ContinuousCurriculumRuntime(promotion.state_dir, object(), scheduler, enabled=True)
    assert restarted._reconcile_promoted_tasks() == 0
