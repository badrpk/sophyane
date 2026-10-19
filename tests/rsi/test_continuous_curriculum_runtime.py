from pathlib import Path

from sophyane.rsi.curriculum import (
    AbilityRecord,
    CurriculumPolicy,
    CurriculumScheduler,
    CurriculumStore,
    CurriculumTask,
    ResourceClass,
    TaskSource,
    TaskStatus,
)
from sophyane.rsi.curriculum_proposals import ProposalResult
from sophyane.rsi.curriculum_runtime import ContinuousCurriculumRuntime


def make_task(task_id: str, parent: str = "seed"):
    return CurriculumTask(
        task_id, parent, "verified task", ("src/example.py",), ("pytest",), TaskSource.CURRICULUM, ResourceClass.LIGHT
    )


class FakeController:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def run_task(self, task):
        self.calls.append(task.task_id)
        return self.results.pop(0)


class FakeProposal:
    def __init__(self, task):
        self.task = task

    def propose(self, _context):
        return ProposalResult(True, self.task, "accepted")


def build(tmp_path: Path, controller, proposal=None, enabled=True, **policy):
    store = CurriculumStore(tmp_path / "curriculum.json")
    scheduler = CurriculumScheduler(store, CurriculumPolicy(cooldown_seconds=0, **policy))
    return ContinuousCurriculumRuntime(
        tmp_path,
        controller,
        scheduler,
        proposal_adapter=proposal,
        enabled=enabled,
    )


def test_runtime_is_opt_in(tmp_path: Path):
    runtime = build(tmp_path, FakeController([]), enabled=False)
    assert runtime.start() is False
    assert runtime.tick()["status"] == "disabled"


def test_verified_ability_enqueues_one_follow_up_and_progresses(tmp_path: Path):
    controller = FakeController([{"status": "VERIFIED", "evidence": ["pytest passed"], "ability": "a1"},
                                 {"status": "VERIFIED", "evidence": ["pytest passed"], "ability": "a2"}])
    runtime = build(tmp_path, controller, FakeProposal(make_task("task-2", "a1")))
    runtime.scheduler.enqueue(make_task("task-1"))

    assert runtime.tick()["status"] == "verified"
    assert runtime.tick()["status"] == "verified"
    assert controller.calls == ["task-1", "task-2"]
    assert runtime.status()["iteration"] == 2
    assert runtime.status()["queue_length"] == 0


def test_failure_is_recorded_without_claiming_ability(tmp_path: Path):
    runtime = build(tmp_path, FakeController([{"status": "ROLLED_BACK", "reason": "verification failed"}]), max_task_attempts=1)
    runtime.scheduler.enqueue(make_task("task-1"))

    result = runtime.tick()

    assert result["status"] == "rolled_back"
    assert runtime.status()["iteration"] == 0
    assert runtime.scheduler._state().queue[0].status is TaskStatus.ROLLED_BACK


def test_restart_paused_task_is_retried_by_continuous_scheduler(tmp_path: Path):
    store = CurriculumStore(tmp_path / "curriculum.json")
    task = make_task("restart-task")
    task.status = TaskStatus.PAUSED
    task.failure_reason = "paused after process restart"
    store.save(__import__("sophyane.rsi.curriculum", fromlist=["CurriculumState"]).CurriculumState(queue=[task]))
    scheduler = CurriculumScheduler(store, CurriculumPolicy(cooldown_seconds=0))

    resumed = scheduler.next_task()

    assert resumed is not None
    assert resumed.task_id == "restart-task"


def test_rejected_attempt_is_retried_before_final_failure(tmp_path: Path):
    controller = FakeController([
        {"status": "REJECTED", "reason": "selected task did not validate"},
        {"status": "VERIFIED", "evidence": ["validator passed"], "ability": "a1"},
    ])
    runtime = build(tmp_path, controller, max_task_attempts=2)
    runtime.scheduler.enqueue(make_task("task-1"))

    assert runtime.tick()["status"] == "retrying"
    assert runtime.tick()["status"] == "verified"
    assert controller.calls == ["task-1", "task-1"]
    assert runtime.status()["iteration"] == 1


def test_restart_recovers_running_task_and_stop_is_durable(tmp_path: Path):
    store = CurriculumStore(tmp_path / "curriculum.json")
    task = make_task("task-1")
    task.status = TaskStatus.RUNNING
    store.save(__import__("sophyane.rsi.curriculum", fromlist=["CurriculumState"]).CurriculumState(queue=[task]))
    runtime = build(tmp_path, FakeController([]))
    assert runtime.scheduler._state().queue[0].status is TaskStatus.PAUSED
    assert runtime.stop("operator") is True
    assert runtime.status()["stopped"] is True


def test_stop_does_not_restart_on_later_tick(tmp_path: Path):
    controller = FakeController([{"status": "VERIFIED", "evidence": ["ok"]}])
    runtime = build(tmp_path, controller)
    runtime.scheduler.enqueue(make_task("task-1"))

    runtime.stop("operator")

    assert runtime.tick()["status"] == "idle"
    assert controller.calls == []
    assert runtime.status()["stopped"] is True


def test_missing_production_task_runner_is_explicitly_paused(tmp_path: Path):
    runtime = build(tmp_path, object())
    runtime.scheduler.enqueue(make_task("task-1"))

    result = runtime.tick()

    assert result["status"] == "paused"
    assert "task runner" in result["reason"]
