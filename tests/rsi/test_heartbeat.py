from pathlib import Path

import pytest

from sophyane.rsi.heartbeat import HeartbeatRecord, HeartbeatStore


def test_heartbeat_round_trips_json(tmp_path: Path):
    store = HeartbeatStore(tmp_path / "heartbeat.json")
    record = HeartbeatRecord(
        worker_id="worker-1",
        pid=123,
        state="running",
        started_at=10.0,
        last_tick_at=12.0,
        current_task_id="task-1",
        last_error="",
        restart_count=2,
    )

    store.save(record)

    assert store.load() == record


def test_touch_atomically_updates_selected_fields(tmp_path: Path):
    store = HeartbeatStore(tmp_path / "heartbeat.json")
    store.save(HeartbeatRecord("worker-1", 123, "running", 10.0, 10.0))

    updated = store.touch(last_tick_at=20.0, state="waiting", current_task_id="task-2")

    assert updated.last_tick_at == 20.0
    assert updated.state == "waiting"
    assert updated.current_task_id == "task-2"
    assert updated.worker_id == "worker-1"


def test_corrupt_heartbeat_fails_closed(tmp_path: Path):
    path = tmp_path / "heartbeat.json"
    path.write_text("not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid heartbeat state"):
        HeartbeatStore(path).load()


def test_stale_age_uses_last_tick(tmp_path: Path):
    record = HeartbeatRecord("worker-1", 123, "running", 10.0, 20.0)

    assert record.is_stale(now=24.9, threshold=5.0) is False
    assert record.is_stale(now=25.0, threshold=5.0) is True
