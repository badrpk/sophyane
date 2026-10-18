from pathlib import Path

import pytest

from sophyane.rsi.heartbeat import HeartbeatRecord, HeartbeatStore
from sophyane.v13_cli import run_curriculum_command


def test_status_includes_heartbeat_diagnostics(tmp_path: Path):
    HeartbeatStore(tmp_path / "heartbeat.json").save(
        HeartbeatRecord("worker", 42, "waiting", 10.0, 20.0, restart_count=3)
    )

    result = run_curriculum_command("status", tmp_path, now=25.0, stale_seconds=10.0)

    assert result["heartbeat"]["state"] == "waiting"
    assert result["heartbeat"]["age_seconds"] == 5.0
    assert result["heartbeat"]["restart_count"] == 3
    assert result["heartbeat"]["stale"] is False


def test_invalid_heartbeat_configuration_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="stale_seconds"):
        run_curriculum_command("status", tmp_path, stale_seconds=0.0)


def test_stop_status_remains_durable_with_heartbeat(tmp_path: Path):
    run_curriculum_command("stop", tmp_path)

    result = run_curriculum_command("status", tmp_path)

    assert result["stopped"] is True
