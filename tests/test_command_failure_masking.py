from pathlib import Path

import sophyane.execution_runtime as runtime


def _progress(_message: str) -> None:
    pass


def _run(tmp_path: Path, command: str):
    return runtime.execute_action(
        {
            "type": "run_command",
            "command": command,
            "timeout": 10,
        },
        tmp_path,
        _progress,
    )


def test_pipeline_missing_executable_is_not_accepted(
    tmp_path: Path,
):
    ok, evidence = _run(
        tmp_path,
        "definitely_missing_sophyane_probe_xyz | sort",
    )

    assert (
        "not found" in evidence.casefold()
        or "no such file" in evidence.casefold()
    )
    assert ok is False


def test_semicolon_missing_executable_is_not_accepted(
    tmp_path: Path,
):
    ok, evidence = _run(
        tmp_path,
        (
            "definitely_missing_sophyane_probe_xyz; "
            "printf 'later-command-ran\\n'"
        ),
    )

    assert "later-command-ran" in evidence

    assert (
        "not found" in evidence.casefold()
        or "no such file" in evidence.casefold()
    )

    assert ok is False


def test_successful_pipeline_remains_accepted(
    tmp_path: Path,
):
    ok, evidence = _run(
        tmp_path,
        "printf 'alpha\\n' | sort",
    )

    assert "Exit code: 0" in evidence
    assert ok is True


def test_successful_semicolon_sequence_remains_accepted(
    tmp_path: Path,
):
    ok, evidence = _run(
        tmp_path,
        "printf 'first\\n'; printf 'second\\n'",
    )

    assert "first" in evidence
    assert "second" in evidence
    assert ok is True


def test_success_with_stderr_warning_remains_accepted(
    tmp_path: Path,
):
    ok, evidence = _run(
        tmp_path,
        (
            "printf 'warning only\\n' >&2; "
            "printf 'success\\n'"
        ),
    )

    assert "warning only" in evidence
    assert "success" in evidence
    assert "Exit code: 0" in evidence
    assert ok is True


def test_and_chain_missing_executable_remains_failure(
    tmp_path: Path,
):
    ok, evidence = _run(
        tmp_path,
        (
            "definitely_missing_sophyane_probe_xyz "
            "&& printf 'never\\n'"
        ),
    )

    assert ok is False

    # The evidence intentionally echoes the submitted command, so the
    # literal word "never" appears in the Command: line even though the
    # right-hand side of && did not execute. Verify STDOUT instead.
    stdout = evidence.split("STDOUT:", 1)[1].split("STDERR:", 1)[0]
    assert "never" not in stdout
