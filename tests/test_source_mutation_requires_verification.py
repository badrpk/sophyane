import json
import shlex
import sys

from sophyane.adaptive_execution import run_adaptive_loop
from sophyane.providers.human_conversation import ProviderResponse
from sophyane.rsi.authority import Operation


def test_source_mutation_continues_to_meaningful_verification(tmp_path):
    target = tmp_path / "verified_source.py"
    ask_calls = []

    initial = ProviderResponse(
        json.dumps(
            {
                "action": {
                    "type": "write_file",
                    "path": "verified_source.py",
                    "content": "VALUE = 42\n",
                }
            }
        ),
        "codex_cli",
    )

    def ask(prompt):
        ask_calls.append(str(prompt))
        return ProviderResponse(
            json.dumps(
                {
                    "action": {
                        "type": "run_command",
                        "command": (
                            f"{shlex.quote(sys.executable)} -c "
                            "\"from pathlib import Path; "
                            "p=Path('verified_source.py'); "
                            "assert p.read_text() == 'VALUE = 42\\\\n'; "
                            "print('verification passed')\""
                        ),
                    }
                }
            ),
            "codex_cli",
        )

    result = run_adaptive_loop(
        initial_text=initial,
        original_request=(
            "Write verified_source.py, then verify the written Python "
            "source before reporting completion."
        ),
        ask=ask,
        workspace=tmp_path,
        max_steps=4,
        operation=Operation.SOPHYANE_SOURCE_MUTATION,
    )

    assert target.read_text(encoding="utf-8") == "VALUE = 42\n"
    assert ask_calls, "successful source mutation must continue to verification"
    assert "verification passed" in result
    assert "implementation and verification completed successfully" in result.lower()
