from __future__ import annotations

import json

from sophyane.adaptive_execution import run_adaptive_loop


class Response:
    def __init__(self, action):
        self.text = json.dumps({"action": action})


def test_failed_required_action_then_successful_command_must_not_false_green(
    tmp_path,
):
    initial = json.dumps(
        {
            "action": {
                "type": "write_file",
                "path": "todo.md",
                "content": "- [ ] required work\n",
            }
        }
    )

    replies = iter(
        [
            # Required mutation fails.
            Response(
                {
                    "type": "run_command",
                    "command": "false",
                }
            ),
            # Provider then performs an unrelated successful observation.
            Response(
                {
                    "type": "run_command",
                    "command": "printf 'still here\\n'",
                }
            ),
            # Once false completion is blocked, the loop may continue.
            # Supply a bounded final response rather than exhausting
            # the mocked provider iterator.
            Response(
                {
                    "type": "respond",
                    "message": "Required execution remains incomplete.",
                }
            ),
        ]
    )

    def ask(_prompt):
        return next(replies)

    result = run_adaptive_loop(
        initial_text=initial,
        original_request=(
            "Create todo.md, then execute a required command that must "
            "succeed, and verify completion. Do not complete while any "
            "required execution step remains failed."
        ),
        ask=ask,
        workspace=tmp_path,
        max_steps=3,
    )

    assert (
        "Project implementation and verification completed successfully."
        not in result
    )


def test_failed_action_then_respond_must_not_erase_failure(
    tmp_path,
):
    initial = json.dumps(
        {
            "action": {
                "type": "run_command",
                "command": "false",
            }
        }
    )

    replies = iter(
        [
            Response(
                {
                    "type": "respond",
                    "message": "Everything is complete.",
                }
            )
        ]
    )

    result = run_adaptive_loop(
        initial_text=initial,
        original_request=(
            "Execute the requested operation successfully. "
            "Do not complete until it succeeds."
        ),
        ask=lambda _prompt: next(replies),
        workspace=tmp_path,
        max_steps=2,
    )

    assert "Everything is complete." not in result
    assert "completed successfully" not in result.casefold()


def test_recovered_failure_may_complete_after_real_success(
    tmp_path,
):
    initial = json.dumps(
        {
            "action": {
                "type": "write_file",
                "path": "probe.txt",
                "content": "ready\n",
            }
        }
    )

    replies = iter(
        [
            Response(
                {
                    "type": "run_command",
                    "command": "false",
                }
            ),
            Response(
                {
                    "type": "run_command",
                    "command": (
                        "test -f probe.txt && "
                        "grep -qx ready probe.txt"
                    ),
                }
            ),
        ]
    )

    result = run_adaptive_loop(
        initial_text=initial,
        original_request=(
            "Create probe.txt containing ready, execute and verify "
            "the requested result."
        ),
        ask=lambda _prompt: next(replies),
        workspace=tmp_path,
        max_steps=3,
    )

    assert "probe.txt" in result
    assert "Execution evidence:" in result
