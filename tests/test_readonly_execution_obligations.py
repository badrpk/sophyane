import json
from types import SimpleNamespace

import sophyane.adaptive_execution as ae
from sophyane.rsi.authority import Operation


ORIGINAL = """
Continue the existing electricity calculator task in this exact directory:
/tmp/sophyane-readonly-obligation

Inspect the existing files. Run all 15 tests and demonstrate the CLI using
that directory as the command working directory.

Do not recreate the files or repeat the deliberately missing executable probe.
Do not modify Sophyane source.

Report actual command output, exit codes, and any unresolved execution failures.
""".strip()


INSPECTION = json.dumps({
    "action": {
        "type": "run_command",
        "command": "pwd && find . -maxdepth 2 -type f -print | sort",
    }
})


PREMATURE = json.dumps({
    "action": {
        "type": "respond",
        "message": (
            "Inspected the workspace. The supplied evidence does not include "
            "execution of all 15 tests or a CLI demonstration, so those "
            "results cannot be claimed as verified."
        ),
    }
})


PYTEST = json.dumps({
    "action": {
        "type": "run_command",
        "command": "python -m pytest -q",
    }
})


CLI = json.dumps({
    "action": {
        "type": "run_command",
        "command": "python electricity_bill.py sample_data.csv",
    }
})


FINAL = json.dumps({
    "action": {
        "type": "respond",
        "message": "Inspection, tests, and CLI demonstration completed.",
    }
})


def response(text):
    return SimpleNamespace(
        text=text,
        provider_id="fixture_provider",
    )


def test_compound_readonly_request_requires_tests_and_cli_before_completion(
    tmp_path,
    monkeypatch,
):
    workspace = tmp_path / "challenge"
    workspace.mkdir()

    (workspace / "electricity_bill.py").write_text(
        "print('ok')\n",
        encoding="utf-8",
    )
    (workspace / "test_electricity_bill.py").write_text(
        "def test_ok(): assert True\n",
        encoding="utf-8",
    )
    (workspace / "sample_data.csv").write_text(
        "units,rate\n1,1\n",
        encoding="utf-8",
    )

    executed = []

    def fake_execute(runtime, action, actual_workspace, progress):
        kind = str(action.get("type") or "").strip().casefold()
        command = str(action.get("command") or "")

        executed.append((kind, command))

        if kind in {
            "run_command",
            "command",
            "run",
            "shell",
            "bash",
        }:
            if "pytest" in command.casefold():
                return (
                    True,
                    "Command: python -m pytest -q\n"
                    "Exit code: 0\n"
                    "STDOUT:\n15 passed in 0.10s\n"
                    "STDERR:\n",
                )

            if "electricity_bill.py" in command:
                return (
                    True,
                    "Command: python electricity_bill.py sample_data.csv\n"
                    "Exit code: 0\n"
                    "STDOUT:\nTotal: 100\n"
                    "STDERR:\n",
                )

            return (
                True,
                "Command: " + command + "\n"
                "Exit code: 0\n"
                "STDOUT:\n"
                + str(actual_workspace)
                + "\n"
                "./electricity_bill.py\n"
                "./sample_data.csv\n"
                "./test_electricity_bill.py\n"
                "STDERR:\n",
            )

        if kind in {"respond", "message"}:
            return (
                True,
                str(
                    action.get("message")
                    or action.get("response")
                    or action.get("content")
                    or ""
                ),
            )

        raise AssertionError(
            f"unexpected action: {action!r}"
        )

    monkeypatch.setattr(ae, "_execute", fake_execute)

    replies = iter([
        response(PREMATURE),
        response(PYTEST),
        response(CLI),
        response(FINAL),
    ])

    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return next(replies)

    result = ae.run_adaptive_loop(
        initial_text=INSPECTION,
        original_request=ORIGINAL,
        ask=ask,
        workspace=workspace,
        max_steps=8,
        operation=Operation.READ_ONLY_OPERATION,
    )

    rendered = str(result)

    commands = [
        command
        for kind, command in executed
        if command
    ]

    print("EXECUTED =", executed)
    print("ASK_COUNT =", len(prompts))
    print("RESULT =", rendered)

    assert any(
        "find . -maxdepth 2 -type f -print" in command
        for command in commands
    )

    assert any(
        "pytest" in command.casefold()
        for command in commands
    ), (
        "required test execution was skipped after inspection"
    )

    assert any(
        "electricity_bill.py" in command
        and "pytest" not in command.casefold()
        for command in commands
    ), (
        "required CLI demonstration was skipped"
    )

    assert "Inspection, tests, and CLI demonstration completed." in rendered


def test_simple_readonly_inspection_can_still_complete(
    tmp_path,
    monkeypatch,
):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "a.py").write_text("x = 1\n", encoding="utf-8")

    request = "Inspect the existing files and report what is present."

    initial = json.dumps({
        "action": {
            "type": "run_command",
            "command": "find . -maxdepth 2 -type f -print | sort",
        }
    })

    final = json.dumps({
        "action": {
            "type": "respond",
            "message": "The repository contains a.py.",
        }
    })

    executed = []

    def fake_execute(runtime, action, actual_workspace, progress):
        kind = str(action.get("type") or "").strip().casefold()
        command = str(action.get("command") or "")
        executed.append((kind, command))

        if kind == "run_command":
            return (
                True,
                "Command: find . -maxdepth 2 -type f -print | sort\n"
                "Exit code: 0\n"
                "STDOUT:\n./a.py\n"
                "STDERR:\n",
            )

        if kind in {"respond", "message"}:
            return True, action.get("message", "")

        raise AssertionError(action)

    monkeypatch.setattr(ae, "_execute", fake_execute)

    replies = iter([response(final)])

    result = ae.run_adaptive_loop(
        initial_text=initial,
        original_request=request,
        ask=lambda prompt: next(replies),
        workspace=workspace,
        max_steps=4,
        operation=Operation.READ_ONLY_OPERATION,
    )

    assert "repository contains a.py" in str(result).casefold()
