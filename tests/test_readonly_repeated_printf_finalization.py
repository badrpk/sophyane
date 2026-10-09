import json
from pathlib import Path

from sophyane import adaptive_execution as adaptive


def test_repeated_printf_does_not_exhaust_readonly_budget(
    tmp_path: Path,
    monkeypatch,
):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "known.txt").write_text(
        "grounded evidence\n",
        encoding="utf-8",
    )

    inspection = "find . -maxdepth 1 -type f -print"
    repeated = "printf '%s\\n' 'Audit conclusion'"

    executed = []
    prompts = []

    def fake_execute(_runtime, action, cwd, _progress):
        command = str(action.get("command") or "")
        executed.append(command)

        if command == inspection:
            return (
                True,
                "Command: find . -maxdepth 1 -type f -print\n"
                "Exit code: 0\n"
                "STDOUT:\n./known.txt\nSTDERR:\n",
            )

        if command == repeated:
            return (
                True,
                "Command: printf\n"
                "Exit code: 0\n"
                "STDOUT:\nAudit conclusion\nSTDERR:\n",
            )

        raise AssertionError(f"Unexpected action: {action!r}")

    monkeypatch.setattr(adaptive, "_execute", fake_execute)

    def ask(prompt):
        prompts.append(prompt)
        return json.dumps({
            "action": {
                "type": "run_command",
                "command": repeated,
            }
        })

    initial = json.dumps({
        "action": {
            "type": "run_command",
            "command": inspection,
        }
    })

    result = adaptive.run_adaptive_loop(
        initial_text=initial,
        original_request=(
            "Inspect this repository read-only and report "
            "the available files. Do not modify anything."
        ),
        ask=ask,
        workspace=workspace,
        max_steps=6,
    )

    assert executed.count(inspection) == 1
    assert executed.count(repeated) <= 1

    # A repeated output-only command must not consume the whole budget.
    assert "Stopped after bounded execution loop" not in str(result)

    # The runtime must not mistake printed text for a verified answer.
    assert (
        "execution stopped safely" in str(result).casefold()
        or "unresolved" in str(result).casefold()
        or "grounded" in str(result).casefold()
        or "inspection completed" in str(result).casefold()
    )

    # Rejected commands must never be reported as executed successes.
    assert executed == [inspection]
    assert "project implementation and verification completed" not in str(result).casefold()
