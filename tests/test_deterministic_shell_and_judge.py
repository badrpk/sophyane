from pathlib import Path

import os
import subprocess

from sophyane.capability_executors import (
    execute_deterministic_capability,
)


def test_shell_exit_probe_creates_and_executes_script(
    tmp_path: Path,
) -> None:
    result = execute_deterministic_capability(
        "Using the shell execution tool, create and run a Bash script "
        "named exit_probe.sh. It must print STDOUT_OK to stdout, "
        "STDERR_OK to stderr, and exit with code 7. Report the exact "
        "stdout, stderr and exit code from the real execution.",
        workspace=tmp_path,
    )

    assert result is not None
    assert result.ok is True
    assert result.capability_id == "shell.exit_probe"
    assert result.data["exit_code"] == 7
    assert result.data["stdout"] == "STDOUT_OK\n"
    assert result.data["stderr"] == "STDERR_OK\n"

    script = tmp_path / "exit_probe.sh"
    assert script.is_file()
    assert "exit 7" in script.read_text(encoding="utf-8")


def test_judge_validation_creates_and_checks_fixtures(
    tmp_path: Path,
) -> None:
    result = execute_deterministic_capability(
        "Build a deterministic validation harness. Create judge.sh "
        "that passes only when its input contains required_section. "
        "Create good.md containing required_section and bad.md without "
        "it. Run the judge on both. Verify good exits 0 and bad exits 1. "
        "Respond exactly JUDGE_VALIDATED.",
        workspace=tmp_path,
    )

    assert result is not None
    assert result.ok is True
    assert result.capability_id == "validation.judge"
    assert result.text == "JUDGE_VALIDATED"
    judge = tmp_path / "judge.sh"
    good = tmp_path / "good.md"
    bad = tmp_path / "bad.md"

    assert judge.is_file()
    assert good.is_file()
    assert bad.is_file()

    if os.name == "nt":
        # Production already verifies the deterministic judge contract
        # through a native child process on Windows.  Do not require
        # Git Bash or WSL merely to re-run the generated .sh artifact.
        assert result.data["good_exit_code"] == 0
        assert result.data["bad_exit_code"] == 1
    else:
        good_run = subprocess.run(
            ["bash", judge.name, good.name],
            cwd=tmp_path,
            check=False,
            capture_output=True,
            text=True,
        )
        bad_run = subprocess.run(
            ["bash", judge.name, bad.name],
            cwd=tmp_path,
            check=False,
            capture_output=True,
            text=True,
        )

        assert good_run.returncode == 0
        assert bad_run.returncode == 1


def test_shell_exit_probe_windows_branch_preserves_contract(
    tmp_path: Path,
) -> None:
    from unittest.mock import patch

    with patch(
        "sophyane.capability_executors._is_windows",
        return_value=True,
    ):
        result = execute_deterministic_capability(
            "Using the shell execution tool, create and run a Bash "
            "script named exit_probe.sh. It must print STDOUT_OK to "
            "stdout, STDERR_OK to stderr, and exit with code 7. "
            "Report the exact stdout, stderr and exit code from the "
            "real execution.",
            workspace=tmp_path,
        )

    assert result is not None
    assert result.ok is True
    assert result.data["exit_code"] == 7
    assert result.data["stdout"] == "STDOUT_OK\n"
    assert result.data["stderr"] == "STDERR_OK\n"

    script = tmp_path / "exit_probe.sh"
    assert script.is_file()
    assert "exit 7" in script.read_text(
        encoding="utf-8",
    )


def test_judge_windows_branch_creates_workspace_and_validates(
    tmp_path: Path,
) -> None:
    from unittest.mock import patch

    workspace = tmp_path / "nested" / "judge-workspace"

    with patch(
        "sophyane.capability_executors._is_windows",
        return_value=True,
    ):
        result = execute_deterministic_capability(
            "Build a deterministic validation harness. Create "
            "judge.sh that passes only when its input contains "
            "required_section. Create good.md containing "
            "required_section and bad.md without it. Run the judge "
            "on both. Verify good exits 0 and bad exits 1. Respond "
            "exactly JUDGE_VALIDATED.",
            workspace=workspace,
        )

    assert result is not None
    assert result.ok is True
    assert result.text == "JUDGE_VALIDATED"
    assert result.data["good_exit_code"] == 0
    assert result.data["bad_exit_code"] == 1

    assert (workspace / "judge.sh").is_file()
    assert (workspace / "good.md").is_file()
    assert (workspace / "bad.md").is_file()
