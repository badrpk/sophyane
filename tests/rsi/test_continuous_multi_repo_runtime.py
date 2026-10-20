"""Daemon rollout controls use durable scheduler and repository state."""

import json
from pathlib import Path
import subprocess

import pytest

from sophyane.rsi.curriculum import CurriculumPolicy, CurriculumScheduler, CurriculumStore, CurriculumTask, TaskSource
from sophyane.rsi.curriculum_proposals import ProposalContext, ProposalResult
from sophyane.rsi.curriculum_runtime import ContinuousCurriculumRuntime
from sophyane.rsi.repository_inventory import RepositoryInventory
from sophyane.rsi_terminal import handle_command, multi_repo_mode, run_multi_repo_cycle


def _git(repo, *args):
    return subprocess.check_output(("git", "-C", str(repo), *args), text=True).strip()


def _runtime(tmp_path):
    roots = tmp_path / "repos"
    roots.mkdir()
    for name in ("alpha", "beta"):
        repo = roots / name
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.name", "Test")
        _git(repo, "config", "user.email", "test@example.invalid")
        (repo / "src").mkdir()
        for filename in ("one.py", "two.py"):
            (repo / "src" / filename).write_text("value = 1\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "base")
        _git(repo, "remote", "add", "origin", f"https://github.com/badrpk/{name}.git")
    state_dir = tmp_path / "state"
    inventory = RepositoryInventory(state_dir / "repository-inventory.json", roots=(roots,), owner="badrpk")
    inventory.refresh()
    calls = []

    class Runner:
        def run_task(self, task):
            calls.append(task.task_id)
            return {"status": "verified", "evidence": ["focused check passed"]}

    scheduler = CurriculumScheduler(CurriculumStore(state_dir / "curriculum.json"), CurriculumPolicy(cooldown_seconds=0))
    runtime = ContinuousCurriculumRuntime(state_dir, Runner(), scheduler, enabled=True)
    runtime.repository_inventory = inventory

    def context_factory():
        record = inventory.next_repository()
        if record is None:
            return None
        return ProposalContext(
            ability=__import__("sophyane.rsi.curriculum", fromlist=["AbilityRecord"]).AbilityRecord("seed", "seed", ()),
            allowed_paths=("src/one.py", "src/two.py"),
            existing_task_ids=(),
            capability_summary="test",
            repository=record,
            repository_id=record.repo_id,
            base_commit=record.commit,
        )

    runtime.context_factory = context_factory

    class Source:
        def __init__(self):
            self.contexts = []

        def propose(self, context):
            self.contexts.append(context)
            name = context.repository.name
            task = CurriculumTask(
                f"task-{name}", "seed", "improve", ("src/one.py",), ("pytest",),
                TaskSource.CURRICULUM, repository_id=context.repository_id,
                base_commit=context.base_commit,
            )
            return ProposalResult(True, task, generator="fixture", review_outcome="approved")

    runtime.task_source = Source()
    return runtime, calls


def test_mode_defaults_to_inventory_and_rejects_unknown_values(monkeypatch):
    monkeypatch.delenv("SOPHYANE_RSI_MULTI_REPO_MODE", raising=False)
    assert multi_repo_mode() == "inventory"
    monkeypatch.setenv("SOPHYANE_RSI_MULTI_REPO_MODE", "proposal")
    assert multi_repo_mode() == "proposal"
    monkeypatch.setenv("SOPHYANE_RSI_MULTI_REPO_MODE", "execute")
    assert multi_repo_mode() == "execute"
    monkeypatch.setenv("SOPHYANE_RSI_MULTI_REPO_MODE", "unrestricted")
    with pytest.raises(ValueError):
        multi_repo_mode()


def test_inventory_advances_cursor_across_restart_and_reports_empty_queue(tmp_path):
    runtime, calls = _runtime(tmp_path)
    assert run_multi_repo_cycle(runtime, "inventory", max_files=1)["status"] == "inventoried"
    assert runtime.repository_inventory.cursor.scanned_commits.keys() == {"badrpk/alpha"}
    restarted = RepositoryInventory(runtime.repository_inventory.state_path, roots=runtime.repository_inventory.roots, owner="badrpk")
    runtime.repository_inventory = restarted
    assert run_multi_repo_cycle(runtime, "inventory", max_files=1)["repository_id"] == "badrpk/beta"
    assert run_multi_repo_cycle(runtime, "inventory", max_files=1)["status"] == "idle"
    assert calls == []
    status = json.loads(handle_command("status", runtime.state_dir))
    assert status["repository_cursor"]["scanned_commits"].keys() == {"badrpk/alpha", "badrpk/beta"}
    assert status["queue_length"] == 0


def test_proposal_mode_caps_files_and_never_executes_queued_task(tmp_path):
    runtime, calls = _runtime(tmp_path)
    result = run_multi_repo_cycle(runtime, "proposal", max_files=1)
    assert result["status"] == "proposed"
    assert runtime.task_source.contexts[0].allowed_paths == ("src/one.py",)
    assert runtime.scheduler.status()["queue_length"] == 1
    assert calls == []
    status = json.loads(handle_command("status", runtime.state_dir))
    assert status["current_repository"] == "badrpk/alpha"
    assert status["current_task_id"] == "task-alpha"
    assert status["last_review_outcome"] == "approved"


def test_execute_mode_runs_only_owning_task_and_reports_result(tmp_path):
    runtime, calls = _runtime(tmp_path)
    result = run_multi_repo_cycle(runtime, "execute", max_files=1)
    assert result["status"] == "verified"
    assert calls == ["task-alpha"]
    status = json.loads(handle_command("status", runtime.state_dir))
    assert status["last_result"]["status"] == "verified"
    assert status["last_result"]["task_id"] == "task-alpha"
    assert status["last_review_outcome"] == "approved"


def test_missing_provider_pauses_without_advancing_cursor(tmp_path):
    runtime, calls = _runtime(tmp_path)
    runtime.task_source = None
    result = run_multi_repo_cycle(runtime, "proposal", max_files=1)
    assert result["status"] == "paused"
    assert runtime.scheduler.status()["paused"] is True
    assert runtime.repository_inventory.cursor.scanned_commits == {}
    assert calls == []


def test_execute_pauses_on_stale_or_unbound_queued_task(tmp_path):
    runtime, calls = _runtime(tmp_path)
    for task_id, repository_id, base_commit in (
        ("unbound", "", ""),
        ("stale", "badrpk/alpha", "0" * 40),
    ):
        task = CurriculumTask(task_id, "seed", "improve", ("src/one.py",), ("pytest",),
                              TaskSource.CURRICULUM, repository_id=repository_id, base_commit=base_commit)
        assert runtime.scheduler.enqueue(task)
        result = run_multi_repo_cycle(runtime, "execute", max_files=1)
        assert result["status"] == "paused"
        assert runtime.scheduler.status()["paused"] is True
        assert runtime.repository_inventory.cursor.scanned_commits == {}
        assert calls == []
        runtime.scheduler.store.save(__import__("sophyane.rsi.curriculum", fromlist=["CurriculumState"]).CurriculumState())


def test_execute_pauses_if_provider_disappears_with_queued_work(tmp_path):
    runtime, calls = _runtime(tmp_path)
    record = runtime.repository_inventory.records[0]
    task = CurriculumTask("queued", "seed", "improve", ("src/one.py",), ("pytest",),
                          TaskSource.CURRICULUM, repository_id=record.repo_id, base_commit=record.commit)
    assert runtime.scheduler.enqueue(task)
    runtime.task_source = None
    assert run_multi_repo_cycle(runtime, "execute", max_files=1)["status"] == "paused"
    assert runtime.scheduler.status()["paused"] is True
    assert runtime.repository_inventory.cursor.scanned_commits == {}
    assert calls == []


def test_execute_runs_bound_queued_task_without_advancing_scan_cursor(tmp_path):
    runtime, calls = _runtime(tmp_path)
    record = runtime.repository_inventory.records[0]
    task = CurriculumTask("queued", "seed", "improve", ("src/one.py",), ("pytest",),
                          TaskSource.CURRICULUM, repository_id=record.repo_id, base_commit=record.commit)
    assert runtime.scheduler.enqueue(task)
    result = run_multi_repo_cycle(runtime, "execute", max_files=1)
    assert result["status"] == "verified"
    assert calls == ["queued"]
    assert runtime.repository_inventory.cursor.scanned_commits == {}


def test_pause_and_stop_are_durable_and_prevent_scans(tmp_path):
    runtime, calls = _runtime(tmp_path)
    handle_command("pause", runtime.state_dir)
    assert run_multi_repo_cycle(runtime, "execute", max_files=1)["status"] == "paused"
    assert runtime.repository_inventory.cursor.scanned_commits == {}
    handle_command("stop", runtime.state_dir)
    assert run_multi_repo_cycle(runtime, "inventory", max_files=1)["status"] == "stopped"
    assert json.loads(handle_command("status", runtime.state_dir))["stopped"] is True
    assert calls == []
