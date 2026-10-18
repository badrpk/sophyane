import json
from pathlib import Path

from sophyane.rsi.observation_bus import autonomous_bus
from sophyane.rsi_terminal import handle_command, runtime_root


def test_status_command_returns_progress_json(tmp_path: Path):
    result = handle_command("status", tmp_path)

    payload = json.loads(result)
    assert "queue_length" in payload
    assert "heartbeat" in payload


def test_hitl_instruction_is_submitted_as_observation(tmp_path: Path):
    result = handle_command("instruction improve the response time", tmp_path)

    assert "accepted" in result.lower()
    observations = autonomous_bus.drain()
    assert observations
    observation, count = observations[0]
    assert count == 1
    assert "improve the response time" in observation.problem


def test_stop_command_is_durable(tmp_path: Path):
    handle_command("stop", tmp_path)

    status = json.loads(handle_command("status", tmp_path))
    assert status["stopped"] is True


def test_runtime_root_switches_to_promoted_live_worktree(tmp_path: Path):
    live = tmp_path / "live-worktree"
    live.mkdir()
    (tmp_path / "promotion.json").write_text(
        '{"promoted":true,"active_commit":"abc"}', encoding="utf-8"
    )

    assert runtime_root(tmp_path) == live
