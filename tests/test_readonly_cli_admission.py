from pathlib import Path

from sophyane import adaptive_execution as ae
from sophyane.rsi.authority import Operation


REQUEST = """
Continue the existing electricity calculator task in this exact directory.

Inspect the existing files. Run all 15 tests and demonstrate the CLI.

Do not recreate the files.
Do not modify Sophyane source.
""".strip()


INSPECTION_ONLY = """
Inspect this repository read-only and explain what files are present.
Do not modify any files.
""".strip()


def _workspace(tmp_path):
    workspace = tmp_path / "challenge"
    workspace.mkdir()

    (workspace / "electricity_bill.py").write_text(
        "print('ok')\n",
        encoding="utf-8",
    )
    (workspace / "sample_data.csv").write_text(
        "units,rate\n1,1\n",
        encoding="utf-8",
    )

    return workspace


def test_explicit_cli_request_admits_existing_python_entrypoint(
    tmp_path,
):
    workspace = _workspace(tmp_path)

    action = {
        "type": "run_command",
        "command": "python electricity_bill.py sample_data.csv",
    }

    assert (
        ae._no_edit_action_problem(
            action,
            original_request=REQUEST,
            workspace=workspace,
        )
        == ""
    )


def test_inspection_only_request_does_not_admit_python_entrypoint(
    tmp_path,
):
    workspace = _workspace(tmp_path)

    action = {
        "type": "run_command",
        "command": "python electricity_bill.py sample_data.csv",
    }

    assert ae._no_edit_action_problem(
        action,
        original_request=INSPECTION_ONLY,
        workspace=workspace,
    )


def test_missing_python_entrypoint_is_not_admitted(
    tmp_path,
):
    workspace = _workspace(tmp_path)

    action = {
        "type": "run_command",
        "command": "python missing.py sample_data.csv",
    }

    assert ae._no_edit_action_problem(
        action,
        original_request=REQUEST,
        workspace=workspace,
    )


def test_python_dash_c_and_stdin_remain_blocked(
    tmp_path,
):
    workspace = _workspace(tmp_path)

    commands = (
        '''python -c "print('x')"''',
        '''python3 -c "print('x')"''',
        "python -",
        "python3 -",
    )

    for command in commands:
        assert ae._no_edit_action_problem(
            {
                "type": "run_command",
                "command": command,
            },
            original_request=REQUEST,
            workspace=workspace,
        ), command


def test_shell_mutations_remain_blocked_with_cli_request(
    tmp_path,
):
    workspace = _workspace(tmp_path)

    commands = (
        "printf x > changed.txt",
        "touch changed.txt",
        "rm -f changed.txt",
    )

    for command in commands:
        assert ae._no_edit_action_problem(
            {
                "type": "run_command",
                "command": command,
            },
            original_request=REQUEST,
            workspace=workspace,
        ), command


def test_batch_propagates_request_aware_cli_authority(
    tmp_path,
):
    workspace = _workspace(tmp_path)

    action = {
        "type": "batch",
        "actions": [
            {
                "type": "run_command",
                "command": "pwd",
            },
            {
                "type": "run_command",
                "command": (
                    "python electricity_bill.py "
                    "sample_data.csv"
                ),
            },
        ],
    }

    assert (
        ae._no_edit_action_problem(
            action,
            original_request=REQUEST,
            workspace=workspace,
        )
        == ""
    )


def test_run_adaptive_loop_admits_explicit_existing_cli(
    tmp_path,
    monkeypatch,
):
    workspace = _workspace(tmp_path)
    executed = []

    def fake_execute(
        runtime,
        action,
        actual_workspace,
        progress,
    ):
        command = str(action.get("command") or "")
        executed.append(command)

        return (
            True,
            "Command: "
            + command
            + "\n"
            "Exit code: 0\n"
            "STDOUT:\n"
            "Total: 100\n"
            "STDERR:\n",
        )

    monkeypatch.setattr(
        ae,
        "_execute",
        fake_execute,
    )

    result = ae.run_adaptive_loop(
        initial_text=(
            '{"action":{"type":"run_command",'
            '"command":"python electricity_bill.py '
            'sample_data.csv"}}'
        ),
        original_request=REQUEST,
        ask=lambda _prompt: (
            '{"action":{"type":"respond",'
            '"message":"CLI demonstration completed."}}'
        ),
        workspace=workspace,
        max_steps=3,
        operation=Operation.READ_ONLY_OPERATION,
    )

    assert any(
        "python electricity_bill.py sample_data.csv"
        in command
        for command in executed
    ), result


def test_context_free_helper_remains_conservative():
    action = {
        "type": "run_command",
        "command": "python electricity_bill.py sample_data.csv",
    }

    assert ae._no_edit_action_problem(action)
    assert (
        ae._no_edit_command_allowed(
            "python electricity_bill.py sample_data.csv"
        )
        is False
    )
