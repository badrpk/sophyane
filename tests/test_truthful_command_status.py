from __future__ import annotations

from pathlib import Path

from sophyane.execution_runtime import execute_action


def test_successful_command_returns_true(
    tmp_path: Path,
) -> None:
    ok, result = execute_action(
        {
            "type": "run_command",
            "command": "exit 0",
            "timeout": 10,
        },
        tmp_path,
        lambda _message: None,
    )

    assert ok is True
    assert "Exit code: 0" in result


def test_failed_command_returns_false(
    tmp_path: Path,
) -> None:
    ok, result = execute_action(
        {
            "type": "run_command",
            "command": "exit 7",
            "timeout": 10,
        },
        tmp_path,
        lambda _message: None,
    )

    assert ok is False
    assert "Exit code: 7" in result
