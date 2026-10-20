import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from sophyane.rsi.curriculum import CurriculumPolicy, CurriculumScheduler, CurriculumStore, CurriculumTask, TaskSource
from sophyane.rsi.curriculum_adapter import AutonomousCurriculumTaskAdapter, NativeEvolutionTaskAdapter
from sophyane.rsi.curriculum_runtime import ContinuousCurriculumRuntime
from sophyane.rsi.curriculum_redgreen import preverify
from sophyane.rsi.models import CommandResult
from sophyane.rsi.repository_inventory import RepositoryRecord
from sophyane.rsi.weakness_ledger import WeaknessLedger


def git(path, *args):
    return subprocess.check_output(("git", "-C", str(path), *args), text=True).strip()


@pytest.fixture
def snapshots(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "src").mkdir()
    (repo / "src" / "value.py").write_text("VALUE = 1\n")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "base")
    commit = git(repo, "rev-parse", "HEAD")
    base = tmp_path / "base"
    candidate = tmp_path / "candidate"
    git(repo, "worktree", "add", "-q", "--detach", str(base), commit)
    git(repo, "worktree", "add", "-q", "--detach", str(candidate), commit)
    record = RepositoryRecord("owner/repo", str(repo), "", "owner", "repo", commit, "main", (("python", "-m", "pytest"),), ("src",), "digest")
    task = CurriculumTask("task-1", "ability", "fix value", ("src/value.py",), ("pytest",), TaskSource.LLM_FOLLOW_UP,
                          component="example", repository_id=record.repo_id, base_commit=commit,
                          red_command=("python", "-m", "pytest", "tests/test_value.py"),
                          red_failure_marker="RSI_WEAKNESS_wrong_value",
                          green_commands=(("python", "-m", "pytest", "tests/test_value.py"),))
    return record, task, base, candidate


def check(command, cwd, *, timeout):
    value = (Path(cwd) / "src" / "value.py").read_text()
    if "VALUE = 1" in value:
        return CommandResult(tuple(command), 1, "AssertionError: RSI_WEAKNESS_wrong_value\n1 failed", str(cwd))
    return CommandResult(tuple(command), 0, "1 passed", str(cwd))


def test_base_declared_failure_then_candidate_success(snapshots):
    record, task, base, candidate = snapshots
    (candidate / "src" / "value.py").write_text("VALUE = 2\n")
    result = preverify(task, record, base, candidate, run=check)
    assert result.status == "verified"
    assert result.base_result.exit_code == 1
    assert tuple(item.exit_code for item in result.candidate_results) == (0,)
    assert result.base_result.command == result.candidate_results[0].command == task.red_command


def test_already_green_skips_candidate_and_promotion(snapshots):
    record, task, base, candidate = snapshots
    (candidate / "src" / "value.py").write_text("VALUE = 2\n")
    calls = []

    def green(_command, _cwd, *, timeout):
        calls.append(_cwd)
        return CommandResult(task.red_command, 0, "1 passed", str(_cwd))

    def factory(_config):
        raise AssertionError("engine must not run")

    manager = SimpleNamespace(promote=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("promoted")))
    gate = lambda selected: preverify(selected, record, base, candidate, run=green)
    result = NativeEvolutionTaskAdapter(record.path, engine_factory=factory, promotion_manager=manager, preverification=gate).run_task(task)
    assert result["status"] == "already_green"
    assert calls == [base]


def test_unrelated_base_failure_is_invalid_red(snapshots):
    record, task, base, candidate = snapshots
    (candidate / "src" / "value.py").write_text("VALUE = 2\n")

    def unrelated(command, cwd, *, timeout):
        return CommandResult(tuple(command), 1, "AssertionError: other_failure\n1 failed", str(cwd))

    result = preverify(task, record, base, candidate, run=unrelated)
    assert result.status == "invalid_red"
    assert result.candidate_results == ()


def test_candidate_failure_is_reported(snapshots):
    record, task, base, candidate = snapshots
    result = preverify(task, record, base, candidate, run=check)
    assert result.status == "candidate_failed"
    assert len(result.candidate_results) == 1


@pytest.mark.parametrize("command", [
    ("sh", "-c", "pytest"),
    ("python", "-c", "print(1)"),
    ("python", "-m", "pytest", "../outside/test.py"),
    ("python", "-m", "pytest", "/tmp/outside.py"),
])
def test_command_escape_is_rejected_before_execution(snapshots, command):
    record, task, base, candidate = snapshots
    result = preverify(replace(task, red_command=command), record, base, candidate,
                       run=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("executed")))
    assert result.status == "infrastructure_error"


def test_candidate_path_escape_is_rejected_before_execution(snapshots, tmp_path):
    record, task, base, candidate = snapshots
    outside = tmp_path / "outside"
    outside.mkdir()
    (candidate / "src" / "escape").symlink_to(outside, target_is_directory=True)
    escaped = replace(task, editable_paths=("src/escape/value.py",))
    result = preverify(escaped, record, base, candidate,
                       run=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("executed")))
    assert result.status == "infrastructure_error"


def test_stale_or_dirty_base_is_not_used(snapshots):
    record, task, base, candidate = snapshots
    (base / "src" / "value.py").write_text("VALUE = 2\n")
    result = preverify(task, record, base, candidate, run=check)
    assert result.status == "infrastructure_error"
    assert result.base_result is None


def test_unbounded_green_plan_is_rejected_before_execution(snapshots):
    record, task, base, candidate = snapshots
    many = tuple(("python", "-m", "pytest", f"tests/test_{index}.py") for index in range(33))
    result = preverify(replace(task, green_commands=many), record, base, candidate,
                       run=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("executed")))
    assert result.status == "infrastructure_error"


def test_bound_autonomous_adapter_requires_preverification(snapshots):
    _record, task, _base, _candidate = snapshots
    controller = SimpleNamespace(ledger=WeaknessLedger(), plans={"example": SimpleNamespace(allowed_paths={"src/value.py"})},
                                 tick=lambda: (_ for _ in ()).throw(AssertionError("ticked")))
    result = AutonomousCurriculumTaskAdapter(controller).run_task(task)
    assert result["status"] == "paused"


def test_already_green_is_terminal_in_runtime(snapshots, tmp_path):
    _record, task, _base, _candidate = snapshots
    store = CurriculumStore(tmp_path / "state.json")
    scheduler = CurriculumScheduler(store, CurriculumPolicy(max_task_attempts=3, cooldown_seconds=0))
    assert scheduler.enqueue(task)
    controller = SimpleNamespace(run_task=lambda _task: {"status": "already_green", "reason": "RED_ALREADY_GREEN"})
    runtime = ContinuousCurriculumRuntime(tmp_path, controller, scheduler, enabled=True)
    result = runtime.tick()
    assert result["status"] == "already_green"
    assert scheduler.status()["queue_length"] == 0
    assert scheduler.next_task() is None
