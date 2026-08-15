from pathlib import Path
import shutil
import subprocess

import pytest

from sophyane.capability_executors import (
    execute_deterministic_capability,
)

BASH_BIN = shutil.which("bash") or shutil.which("sh")
pytestmark = pytest.mark.skipif(
    not BASH_BIN,
    reason="Deterministic shell and judge capabilities require bash",
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

    good_run = subprocess.run(
        [BASH_BIN, judge.name, good.name],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    bad_run = subprocess.run(
        [BASH_BIN, judge.name, bad.name],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert good_run.returncode == 0
    assert bad_run.returncode == 1
