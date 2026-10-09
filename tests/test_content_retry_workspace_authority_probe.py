import json
from pathlib import Path

import pytest


def test_readonly_content_retry_keeps_explicit_workspace(
    monkeypatch,
    tmp_path,
):
    """
    Causal regression for the live failure:

    An explicit external repository must remain authoritative
    after a failed read-only inspection command and during the
    provider's retry.
    """
    from pathlib import Path

    import sophyane.adaptive_execution as adaptive
    import sophyane.execution_runtime as execution_runtime

    requested = tmp_path / "requested_repository"
    requested.mkdir()

    (requested / "plant_config.py").write_text(
        'PLANT_NAME = "Chakwal Alpha"\n'
        'FURNACES = 3\n'
        'FURNACE_MW = 2\n'
        'ROLLING_MW = 2\n'
        'CCM_MW = 2\n',
        encoding="utf-8",
    )

    executed_workspaces = []
    executed_commands = []

    real_which = adaptive.shutil.which

    def fake_which(command):
        if command == "rg":
            return "/synthetic-test-bin/rg"
        return real_which(command)

    monkeypatch.setattr(
        adaptive.shutil,
        "which",
        fake_which,
    )

    def fake_execute_action(
        action,
        workspace,
        progress,
    ):
        resolved = Path(workspace).resolve()

        executed_workspaces.append(
            str(resolved)
        )

        command = str(
            action.get("command")
            or action.get("cmd")
            or ""
        )

        executed_commands.append(command)

        if len(executed_workspaces) == 1:
            return (
                False,
                "Command: "
                + command
                + "\n"
                + "Exit code: 127\n"
                + "STDOUT:\n"
                + "STDERR:\n"
                + "/bin/sh: rg: not found",
            )

        return (
            True,
            "Command: "
            + command
            + "\n"
            + "Exit code: 0\n"
            + "STDOUT:\n"
            + '1:PLANT_NAME = "Chakwal Alpha"\n'
            + "2:FURNACES = 3\n"
            + "3:FURNACE_MW = 2\n"
            + "4:ROLLING_MW = 2\n"
            + "5:CCM_MW = 2\n"
            + "STDERR:\n",
        )

    monkeypatch.setattr(
        execution_runtime,
        "execute_action",
        fake_execute_action,
    )

    responses = iter(
        [
            json.dumps({
                "action": "run_command",
                "command": (
                    "grep -nE "
                    "'PLANT_NAME|FURNACES|FURNACE_MW|"
                    "ROLLING_MW|CCM_MW' "
                    "plant_config.py"
                ),
            }),
            json.dumps({"action": {"type": "respond", "text": "Chakwal Alpha has 3 furnaces at "
                "2 MW each; total configured "
                "equipment is 10 MW."}}),
        ]
    )

    final_answer = (
        "Chakwal Alpha has 3 furnaces at "
        "2 MW each; total configured "
        "equipment is 10 MW."
    )

    def ask(_prompt):
        try:
            return next(responses)
        except StopIteration:
            # The adaptive loop may perform an additional
            # completion check after the successful retry.
            # Repeating the final textual answer is safe;
            # never fabricate another executable action.
            return final_answer

    initial_text = json.dumps({
        "action": "run_command",
        "command": (
            "rg -n "
            "'PLANT_NAME|FURNACES|FURNACE_MW|"
            "ROLLING_MW|CCM_MW' "
            "plant_config.py"
        ),
    })

    request = (
        f"Work only in this exact repository: "
        f"{requested}\n"
        "Read plant_config.py read-only and report "
        "plant name, furnace count, furnace MW, "
        "and total MW. Do not modify anything."
    )

    from sophyane.rsi.authority import Operation

    result = adaptive.run_adaptive_loop(
        initial_text=initial_text,
        original_request=request,
        ask=ask,
        workspace=requested,
        max_steps=6,
        operation=Operation.READ_ONLY_OPERATION,
    )

    expected = str(requested.resolve())

    assert len(executed_workspaces) >= 2, (
        "The causal sequence did not reach the "
        "retry execution: "
        f"{executed_workspaces!r}"
    )

    assert executed_workspaces[0] == expected, (
        "Initial read-only execution escaped the "
        "explicit workspace: "
        f"expected={expected!r}, "
        f"actual={executed_workspaces[0]!r}"
    )

    assert executed_workspaces[1] == expected, (
        "Read-only repair/retry lost explicit "
        "workspace authority: "
        f"expected={expected!r}, "
        f"actual={executed_workspaces[1]!r}"
    )

    assert all(
        workspace == expected
        for workspace in executed_workspaces
    ), (
        "At least one execution escaped the "
        "explicit workspace: "
        f"{executed_workspaces!r}"
    )

    assert executed_commands[0].startswith("rg ")
    assert executed_commands[1].startswith("grep ")

    assert "Chakwal Alpha" in str(result)
