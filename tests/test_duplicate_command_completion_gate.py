from pathlib import Path

from sophyane import adaptive_execution as adaptive


def test_both_duplicate_completion_components_are_installed():
    source = Path(
        adaptive.__file__
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "SOPHYANE_DUPLICATE_COMMAND_COMPLETION_GATE_V1"
        in source
    )

    assert (
        "SOPHYANE_DUPLICATE_READ_ONLY_INSPECTION_V1"
        in source
    )

    assert (
        "not _is_read_only_inspection_command("
        in source
    )


def test_exact_r2_sed_command_is_inspection():
    assert adaptive._is_read_only_inspection_command(
        "sed -n '1,260p' test_app.py"
    )


def test_read_only_family_is_blocked_from_duplicate_completion():
    commands = [
        "cat app.py",
        "head -n 20 app.py",
        "tail -n 20 app.py",
        "sed -n '1,260p' test_app.py",
        "grep -n health app.py",
        "find . -maxdepth 2 -type f",
        "ls -la",
        "stat app.py",
        "wc -l app.py",
        "pwd",
        "readlink app.py",
        "realpath app.py",
        "git status --porcelain=v1",
        "git diff -- app.py",
        "git show HEAD:app.py",
        "git log -1",
        "git rev-parse HEAD",
        "git ls-files",
    ]

    for command in commands:
        assert adaptive._is_read_only_inspection_command(
            command
        ), command


def test_mutation_and_verification_commands_are_not_inspection():
    commands = [
        "python -m pytest -q",
        "python -m unittest -v",
        "python -m py_compile app.py",
        "mkdir build",
        "touch result.txt",
        "cp a.py b.py",
        "mv a.py b.py",
        "rm stale.txt",
        "git add app.py",
        "git commit -m test",
    ]

    for command in commands:
        assert not adaptive._is_read_only_inspection_command(
            command
        ), command


def test_exact_r2_duplicate_sed_cannot_complete():
    command = "sed -n '1,260p' test_app.py"

    synthetic = (
        f"Command: {command}\n"
        "Exit code: 0\n"
        "STDOUT:\n"
        "previously successful\n"
        "STDERR:\n"
    )

    meaningful = (
        adaptive.verification_result_is_meaningful(
            command,
            synthetic,
        )
    )

    allowed = (
        not adaptive._is_read_only_inspection_command(
            command
        )
        and meaningful
    )

    assert allowed is False


def test_pytest_duplicate_can_still_be_meaningful_verification():
    command = "python -m pytest -q"

    synthetic = (
        f"Command: {command}\n"
        "Exit code: 0\n"
        "STDOUT:\n"
        "2 passed in 0.04s\n"
        "STDERR:\n"
    )

    assert not adaptive._is_read_only_inspection_command(
        command
    )

    assert adaptive.verification_result_is_meaningful(
        command,
        synthetic,
    )
