from __future__ import annotations

import json

from sophyane.adaptive_execution import (
    run_adaptive_loop,
)


def test_successful_targeted_patch_completes_without_provider_followup(
    tmp_path,
):
    target = tmp_path / "probe.txt"
    target.write_text(
        "BOOTSTRAP_BEFORE\n",
        encoding="utf-8",
    )

    initial_text = json.dumps(
        {
            "action": {
                "type": "targeted_patch",
                "path": "probe.txt",
                "old": "BOOTSTRAP_BEFORE",
                "new": "BOOTSTRAP_AFTER",
            }
        }
    )

    followup_calls = []

    def ask(prompt: str):
        followup_calls.append(prompt)
        raise AssertionError(
            "provider follow-up must not be required "
            "after a successful targeted_patch"
        )

    result = run_adaptive_loop(
        initial_text=initial_text,
        original_request=(
            "Modify probe.txt. Replace exactly "
            "BOOTSTRAP_BEFORE with BOOTSTRAP_AFTER. "
            "Do not modify any other file. "
            "Execute the edit and return the verified result."
        ),
        ask=ask,
        workspace=tmp_path,
        max_steps=16,
    )

    assert target.read_text(
        encoding="utf-8"
    ) == "BOOTSTRAP_AFTER\n"

    assert followup_calls == []

    assert "Execution evidence:" in result
    assert "Patched" in result


def test_failed_targeted_patch_does_not_claim_completion(
    tmp_path,
):
    target = tmp_path / "probe.txt"
    target.write_text(
        "SOMETHING_ELSE\n",
        encoding="utf-8",
    )

    initial_text = json.dumps(
        {
            "action": {
                "type": "targeted_patch",
                "path": "probe.txt",
                "old": "BOOTSTRAP_BEFORE",
                "new": "BOOTSTRAP_AFTER",
            }
        }
    )

    prompts = []

    class Response:
        text = json.dumps(
            {
                "action": {
                    "type": "respond",
                    "message": "unable to patch",
                }
            }
        )

    def ask(prompt: str):
        prompts.append(prompt)
        return Response()

    result = run_adaptive_loop(
        initial_text=initial_text,
        original_request=(
            "Replace BOOTSTRAP_BEFORE "
            "with BOOTSTRAP_AFTER in probe.txt."
        ),
        ask=ask,
        workspace=tmp_path,
        max_steps=4,
    )

    assert prompts
    assert target.read_text(
        encoding="utf-8"
    ) == "SOMETHING_ELSE\n"

    assert (
        "Project implementation and verification "
        "completed successfully."
        not in result
    )


echo = None
