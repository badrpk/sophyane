from pathlib import Path

from sophyane.rsi.curriculum import (
    CurriculumScheduler,
    CurriculumStore,
    CurriculumTask,
    ResourceClass,
    TaskSource,
    TaskStatus,
    CurriculumPolicy,
)


def task(task_id: str, source: TaskSource, created_at: float = 1.0) -> CurriculumTask:
    return CurriculumTask(
        task_id=task_id,
        parent_ability_id="ability-1",
        objective=task_id,
        editable_paths=("src/example.py",),
        verification=("python", "-m", "pytest"),
        source=source,
        resource_class=ResourceClass.LIGHT,
        created_at=created_at,
    )


def scheduler(tmp_path: Path, now=lambda: 100.0, **kwargs):
    return CurriculumScheduler(
        CurriculumStore(tmp_path / "curriculum.json"),
        CurriculumPolicy(**kwargs),
        clock=now,
    )


def test_priority_is_deterministic(tmp_path: Path):
    runtime = scheduler(tmp_path)
    runtime.enqueue(task("llm", TaskSource.LLM_FOLLOW_UP))
    runtime.enqueue(task("gap", TaskSource.CAPABILITY_GAP))
    runtime.enqueue(task("regression", TaskSource.REGRESSION))

    assert runtime.next_task().task_id == "regression"


def test_duplicate_task_ids_are_rejected(tmp_path: Path):
    runtime = scheduler(tmp_path)
    assert runtime.enqueue(task("same", TaskSource.CURRICULUM)) is True
    assert runtime.enqueue(task("same", TaskSource.CURRICULUM)) is False


def test_verified_task_records_one_follow_up_budget(tmp_path: Path):
    runtime = scheduler(tmp_path, max_follow_ups=1)
    runtime.enqueue(task("first", TaskSource.CURRICULUM))
    running = runtime.next_task()
    runtime.mark_running(running.task_id)
    runtime.record_verified(running.task_id, ("pytest: 1 passed",))

    assert runtime.status()["iteration"] == 1
    assert runtime.can_enqueue_follow_up() is True
    runtime.mark_follow_up_enqueued()
    assert runtime.can_enqueue_follow_up() is False


def test_pause_stop_and_cooldown_block_work(tmp_path: Path):
    current = [100.0]
    runtime = scheduler(tmp_path, now=lambda: current[0], cooldown_seconds=10)
    runtime.enqueue(task("first", TaskSource.CURRICULUM))
    running = runtime.next_task()
    runtime.mark_running(running.task_id)
    runtime.record_verified(running.task_id, ("ok",))
    runtime.enqueue(task("second", TaskSource.CURRICULUM))
    assert runtime.next_task() is None

    runtime.pause("operator requested pause")
    current[0] += 20
    assert runtime.next_task() is None
    runtime.resume()
    assert runtime.next_task().task_id == "second"
    runtime.stop("test complete")
    assert runtime.next_task() is None


def test_iteration_and_wall_clock_budgets_pause_scheduler(tmp_path: Path):
    current = [100.0]
    runtime = scheduler(
        tmp_path,
        now=lambda: current[0],
        max_iterations=1,
        max_wall_seconds=5,
    )
    runtime.enqueue(task("first", TaskSource.CURRICULUM))
    running = runtime.next_task()
    runtime.mark_running(running.task_id)
    runtime.record_verified(running.task_id, ("ok",))
    runtime.enqueue(task("second", TaskSource.CURRICULUM))
    assert runtime.next_task() is None

    current[0] += 10
    assert runtime.status()["paused"] is True
