from pathlib import Path

import pytest

from sophyane.rsi.curriculum import (
    AbilityRecord,
    CurriculumState,
    CurriculumStore,
    CurriculumTask,
    ResourceClass,
    TaskSource,
    TaskStatus,
)


def make_task(task_id: str = "task-1") -> CurriculumTask:
    return CurriculumTask(
        task_id=task_id,
        parent_ability_id="seed",
        objective="Add a verified smoke ability",
        editable_paths=("src/sophyane/rsi/example.py",),
        verification=("python", "-m", "pytest"),
        source=TaskSource.CAPABILITY_GAP,
        resource_class=ResourceClass.LIGHT,
    )


def test_curriculum_state_round_trips_json(tmp_path: Path):
    store = CurriculumStore(tmp_path / "curriculum.json")
    state = CurriculumState(
        queue=[make_task()],
        abilities=[AbilityRecord("seed", "seed ability", ("seed evidence",))],
    )

    store.save(state)

    loaded = store.load()
    assert loaded.queue[0] == state.queue[0]
    assert loaded.abilities[0] == state.abilities[0]
    assert loaded.schema_version == 1


def test_corrupt_state_fails_closed(tmp_path: Path):
    path = tmp_path / "curriculum.json"
    path.write_text("not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid curriculum state"):
        CurriculumStore(path).load()


def test_running_task_recovers_as_paused(tmp_path: Path):
    store = CurriculumStore(tmp_path / "curriculum.json")
    task = make_task()
    task.status = TaskStatus.RUNNING
    store.save(CurriculumState(queue=[task]))

    loaded = store.load()
    assert loaded.queue[0].status is TaskStatus.PAUSED
    assert "restart" in loaded.queue[0].failure_reason.lower()


def test_append_event_is_auditable(tmp_path: Path):
    store = CurriculumStore(tmp_path / "curriculum.json")
    store.append_event({"event": "created", "task_id": "task-1"})

    events = (tmp_path / "curriculum.events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(events) == 1
    assert '"task_id": "task-1"' in events[0]
