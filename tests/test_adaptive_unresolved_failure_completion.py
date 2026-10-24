from __future__ import annotations

import json

import pytest

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


@pytest.mark.parametrize(
    ("marker", "failure_name"),
    [
        ("zero_battery.ready", "zero-battery failure"),
        ("solar_capacity.ready", "solar-capacity mismatch"),
    ],
)
def test_failed_verification_calls_one_repair_then_reruns_exact_command(
    tmp_path,
    marker,
    failure_name,
):
    command = f"test -f {marker}"
    initial = json.dumps(
        {
            "action": {
                "type": "run_command",
                "command": command,
                "deterministic_post_bundle_verification": "test",
            }
        }
    )
    prompts = []
    responses = iter(
        [
            Response(
                {
                    "type": "write_file",
                    "path": marker,
                    "content": f"repaired {failure_name}\n",
                }
            )
        ]
    )

    def ask(prompt):
        prompts.append(prompt)
        return next(responses)

    result = run_adaptive_loop(
        initial_text=initial,
        original_request=(
            f"Repair the {failure_name} in the generated application, "
            "then rerun the exact verification command."
        ),
        ask=ask,
        workspace=tmp_path,
        max_steps=6,
    )

    assert "completed successfully" in result.casefold()
    assert len(prompts) == 1
    assert (tmp_path / marker).is_file()
    assert result.count(command) >= 2


def test_failed_verification_repair_budget_is_not_reset_by_repair_writes(
    tmp_path,
):
    command = "test -f first.ready && test -f second.ready"
    initial = json.dumps(
        {
            "action": {
                "type": "run_command",
                "command": command,
                "deterministic_post_bundle_verification": "test",
            }
        }
    )
    prompts = []
    responses = iter(
        [
            Response(
                {
                    "type": "write_file",
                    "path": "first.ready",
                    "content": "first\n",
                }
            ),
            Response(
                {
                    "type": "write_file",
                    "path": "still-unfixed.txt",
                    "content": "repair attempt\n",
                }
            ),
        ]
    )

    def ask(prompt):
        prompts.append(prompt)
        return next(responses)

    result = run_adaptive_loop(
        initial_text=initial,
        original_request="Repair the energy simulator and rerun its tests.",
        ask=ask,
        workspace=tmp_path,
        max_steps=8,
    )

    assert "completed successfully" not in result.casefold()
    assert "bounded verification repair attempts" in result.casefold()
    assert len(prompts) == 2


def test_failed_full_stack_test_calls_one_repair_then_replays_exact_command(
    tmp_path,
    monkeypatch,
):
    command = "test -f full_stack.ready"
    initial = json.dumps(
        {
            "action": {
                "type": "run_command",
                "command": command,
                "deterministic_post_bundle_verification": "full_stack_test",
            }
        }
    )
    prompts = []
    responses = iter(
        [
            Response(
                {
                    "type": "write_file",
                    "path": "full_stack.ready",
                    "content": "repaired\n",
                }
            )
        ]
    )

    def ask(prompt):
        prompts.append(prompt)
        return next(responses)

    monkeypatch.setattr(
        "sophyane.full_stack_verification.verify_full_stack_application",
        lambda _workspace, _progress: (True, "fabric ok"),
    )

    result = run_adaptive_loop(
        initial_text=initial,
        original_request=(
            "Repair the full-stack application, then rerun its exact "
            "verification command."
        ),
        ask=ask,
        workspace=tmp_path,
        max_steps=8,
    )

    assert "completed successfully" in result.casefold()
    assert len(prompts) == 1
    assert (tmp_path / "full_stack.ready").is_file()
    assert result.count(command) >= 2


def test_failed_service_fabric_verification_repairs_then_rechecks(
    tmp_path,
    monkeypatch,
):
    initial = json.dumps(
        {
            "action": {
                "type": "run_command",
                "command": "true",
                "deterministic_post_bundle_verification": "full_stack_test",
            }
        }
    )
    prompts = []
    responses = iter(
        [
            Response(
                {
                    "type": "write_file",
                    "path": "fabric.ready",
                    "content": "repaired\n",
                }
            )
        ]
    )
    fabric_results = iter(
        [
            (False, "fabric rejected the application"),
            (True, "fabric ok"),
        ]
    )

    def ask(prompt):
        prompts.append(prompt)
        return next(responses)

    monkeypatch.setattr(
        "sophyane.full_stack_verification.verify_full_stack_application",
        lambda _workspace, _progress: next(fabric_results),
    )

    result = run_adaptive_loop(
        initial_text=initial,
        original_request="Repair the full-stack application and verify it.",
        ask=ask,
        workspace=tmp_path,
        max_steps=8,
    )

    assert "completed successfully" in result.casefold()
    assert len(prompts) == 1
    assert (tmp_path / "fabric.ready").is_file()
