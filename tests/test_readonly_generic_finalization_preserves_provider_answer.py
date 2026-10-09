from pathlib import Path
from types import SimpleNamespace

import pytest

from sophyane import adaptive_execution


ORIGINAL = """Continue the existing electricity calculator task in this exact directory:
/tmp/sophyane-readonly-generic-finalization

Inspect the existing files. Run all 15 tests and demonstrate the CLI using
that directory as the command working directory.

Do not recreate the files or repeat the deliberately missing executable probe.
Do not modify Sophyane source.

Report actual command output, exit codes, and any unresolved execution failures.
"""


def test_grounded_provider_final_answer_survives_generic_readonly_finalization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    Regression contract:

    Once all explicit read-only execution obligations are satisfied, a
    provider's grounded final answer must remain authoritative.

    The generic "no implementation target was specified" execution result
    must not replace that provider answer with the runtime's generic
    "Read-only repository inspection completed" synthesis.
    """

    workspace = tmp_path / "repo"
    workspace.mkdir()

    (workspace / "electricity_bill.py").write_text(
        "print('Total: 100')\n",
        encoding="utf-8",
    )
    (workspace / "sample_data.csv").write_text(
        "usage\n100\n",
        encoding="utf-8",
    )

    replies = iter(
        [
            SimpleNamespace(
                provider_id="codex_cli",
                text=(
                    '{"action":{"type":"run_command",'
                    '"command":"pwd && find . -maxdepth 2 -type f -print | sort"}}'
                ),
            ),
            SimpleNamespace(
                provider_id="codex_cli",
                text=(
                    '{"action":{"type":"run_command",'
                    '"command":"python -m pytest -q"}}'
                ),
            ),
            SimpleNamespace(
                provider_id="codex_cli",
                text=(
                    '{"action":{"type":"run_command",'
                    '"command":"python electricity_bill.py sample_data.csv"}}'
                ),
            ),
            SimpleNamespace(
                provider_id="codex_cli",
                text=(
                    '{"action":{"type":"respond",'
                    '"message":"Inspection completed. All 15 tests passed with '
                    'exit code 0. The CLI completed with exit code 0 and '
                    'reported Total: 100. No unresolved execution failures '
                    'remain."}}'
                ),
            ),
        ]
    )

    executed = []

    def ask(_prompt):
        return next(replies)

    def fake_execute(_runtime, action, cwd, _progress):
        kind = str(action.get("type") or "").casefold()
        command = str(action.get("command") or "")

        executed.append((kind, command, str(cwd)))

        if kind == "run_command":
            if "pytest" in command:
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
                "Command: pwd && find . -maxdepth 2 -type f -print | sort\n"
                "Exit code: 0\n"
                f"STDOUT:\n{cwd}\n"
                "./electricity_bill.py\n"
                "./sample_data.csv\n"
                "STDERR:\n",
            )

        if kind in {"respond", "message"}:
            # This reproduces the generic runtime execution result that
            # currently activates the line-3510 finalization branch.
            return True, "no implementation target was specified"

        raise AssertionError(f"unexpected action: {action!r}")

    monkeypatch.setattr(
        adaptive_execution,
        "_execute",
        fake_execute,
    )

    result = adaptive_execution.run_adaptive_loop(
        initial_text=next(replies),
        original_request=ORIGINAL,
        ask=ask,
        workspace=workspace,
        max_steps=8,
        progress=lambda _message: None,
    )

    rendered = str(result)

    assert any(
        "find . -maxdepth 2" in command
        for kind, command, _cwd in executed
        if kind == "run_command"
    )

    assert any(
        "pytest" in command
        for kind, command, _cwd in executed
        if kind == "run_command"
    )

    assert any(
        "electricity_bill.py" in command
        for kind, command, _cwd in executed
        if kind == "run_command"
    )

    # All execution obligations were genuinely satisfied.
    assert "15 passed" in rendered
    assert "Total: 100" in rendered

    # Most importantly: preserve the grounded provider final answer.
    assert (
        "Inspection completed. All 15 tests passed with exit code 0. "
        "The CLI completed with exit code 0 and reported Total: 100. "
        "No unresolved execution failures remain."
        in rendered
    )

    # The generic runtime synthesis must not replace it.
    assert (
        "Read-only repository inspection completed."
        not in rendered
    )
