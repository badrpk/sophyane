import json
from pathlib import Path

import pytest

from sophyane.v13_cli import run_curriculum_command


def test_start_status_pause_stop_are_durable(tmp_path: Path):
    assert run_curriculum_command("start", tmp_path)["status"] == "started"
    assert run_curriculum_command("status", tmp_path)["paused"] is False
    assert run_curriculum_command("pause", tmp_path)["status"] == "paused"
    assert run_curriculum_command("stop", tmp_path)["status"] == "stopped"
    assert run_curriculum_command("status", tmp_path)["stopped"] is True


def test_status_is_json_serializable(tmp_path: Path):
    result = run_curriculum_command("status", tmp_path)
    assert json.dumps(result)
    assert "queue_length" in result
    assert "iteration" in result


def test_invalid_policy_values_are_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="max_iterations"):
        run_curriculum_command("status", tmp_path, max_iterations=0)
