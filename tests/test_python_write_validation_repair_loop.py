from __future__ import annotations

import json
from pathlib import Path

from sophyane.adaptive_execution import run_adaptive_loop


def test_malformed_python_is_repaired_before_next_file(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    # This is deliberately valid JSON whose decoded Python content is
    # syntactically invalid because a literal newline appears inside the
    # single-quoted Python string.
    initial = json.dumps(
        {
            "action": {
                "type": "write_file",
                "path": "backend/app.py",
                "content": (
                    "print('Starting httpd...\n"
                    "')\n"
                ),
            }
        }
    )

    repaired_source = (
        "print('Starting httpd...')\n"
    )

    responses = iter(
        [
            # First provider call must be the focused repair triggered by
            # immediate Python syntax validation.
            json.dumps(
                {
                    "action": {
                        "type": "write_file",
                        "path": "backend/app.py",
                        "content": repaired_source,
                    }
                }
            ),

            # After the corrected source validates, completion is allowed.
            json.dumps(
                {
                    "action": {
                        "type": "respond",
                        "message": "repair complete",
                    }
                }
            ),
        ]
    )

    def ask(prompt: str):
        calls.append(prompt)
        return next(responses)

    result = run_adaptive_loop(
        initial_text=initial,
        original_request=(
            "Create backend/app.py and verify it. "
            "This is a local Python software project."
        ),
        ask=ask,
        workspace=tmp_path,
        max_steps=8,
        progress=lambda _message: None,
    )

    target = tmp_path / "backend" / "app.py"

    assert target.is_file()

    final_source = target.read_text(
        encoding="utf-8",
    )

    assert final_source == repaired_source

    # The malformed file must trigger a provider repair call.
    assert calls

    first_prompt = calls[0].lower()

    assert (
        "python syntax validation failed"
        in first_prompt
    )

    assert (
        "repair this exact file"
        in first_prompt
    )

    assert (
        "backend/app.py"
        in first_prompt
    )

    # It must not silently continue to another generated file.
    assert not (
        tmp_path / "another.py"
    ).exists()

    assert (
        "repair complete"
        in result.lower()
        or "execution evidence"
        in result.lower()
    )


def test_exact_previous_qwen_failure_is_rejected(
    tmp_path: Path,
) -> None:
    initial = json.dumps(
        {
            "action": {
                "type": "write_file",
                "path": "backend/app.py",
                "content": (
                    "import sqlite3\n"
                    "from http.server import "
                    "BaseHTTPRequestHandler, HTTPServer\n"
                    "\n"
                    "if __name__ == '__main__':\n"
                    "    print('Starting httpd...\n"
                    "')\n"
                ),
            }
        }
    )

    observed: list[str] = []

    def ask(prompt: str):
        observed.append(prompt)

        # Stop immediately after proving which repair prompt the loop
        # generated. A valid completion action avoids any real provider.
        return json.dumps(
            {
                "action": {
                    "type": "respond",
                    "message": "diagnostic stop",
                }
            }
        )

    run_adaptive_loop(
        initial_text=initial,
        original_request=(
            "Create and validate backend/app.py as a "
            "local Python software project."
        ),
        ask=ask,
        workspace=tmp_path,
        max_steps=4,
        progress=lambda _message: None,
    )

    assert observed

    repair = observed[0].lower()

    assert "python syntax validation failed" in repair
    assert "backend/app.py" in repair
    assert "unterminated string literal" in repair


def test_invalid_action_and_python_validation_share_repair_budget(
    tmp_path: Path,
) -> None:
    """Different failure classes share one consecutive repair budget."""

    calls: list[str] = []

    initial = json.dumps(
        {
            "action": {
                "type": "run_command",
                "command": "implement app.py",
            }
        }
    )

    malformed_write = json.dumps(
        {
            "action": {
                "type": "write_file",
                "path": "app.py",
                "content": "print('broken\n')\n",
            }
        }
    )

    malformed_repair = json.dumps(
        {
            "action": {
                "type": "write_file",
                "path": "app.py",
                "content": "print('still broken\n')\n",
            }
        }
    )

    forbidden_extra_repair = json.dumps(
        {
            "action": {
                "type": "write_file",
                "path": "app.py",
                "content": (
                    "print('unexpected extra repair')\n"
                ),
            }
        }
    )

    responses = iter(
        [
            malformed_write,
            malformed_repair,
            forbidden_extra_repair,
        ]
    )

    def ask(prompt: str):
        calls.append(prompt)
        return next(responses)

    result = run_adaptive_loop(
        initial_text=initial,
        original_request=(
            "Create app.py as a local Python software project."
        ),
        ask=ask,
        workspace=tmp_path,
        max_steps=8,
        progress=lambda _message: None,
    )

    # Consecutive failure sequence:
    #
    # 1. invalid command -> repair call 1
    # 2. malformed Python -> repair call 2
    # 3. malformed Python -> bounded stop
    #
    # A third repair call would prove that the failure classes
    # are receiving separate/reset repair allowances.
    assert len(calls) == 2

    assert (
        "Execution stopped safely after bounded repair attempts."
        in result
    )

    target = tmp_path / "app.py"
    assert target.is_file()

    assert (
        target.read_text(encoding="utf-8")
        != "print('unexpected extra repair')\n"
    )

    assert (
        "rejected unsafe/invalid command action"
        in calls[0].lower()
    )

    assert (
        "python syntax validation failed"
        in calls[1].lower()
    )


def test_python_repair_prompt_contains_current_broken_target_content(
    tmp_path: Path,
) -> None:
    """Python repair must be grounded in the exact failed artifact."""

    broken_source = (
        "from decimal import Decimal\n"
        "\n"
        "DISTINCTIVE_REPAIR_CONTEXT = 'inventory-model-v1'\n"
        "\n"
        "def parse_price(value: str) -> Decimal:\n"
        "    if not value:\n"
        "    return Decimal(value)\n"
    )

    repaired_source = (
        "from decimal import Decimal\n"
        "\n"
        "DISTINCTIVE_REPAIR_CONTEXT = 'inventory-model-v1'\n"
        "\n"
        "def parse_price(value: str) -> Decimal:\n"
        "    if not value:\n"
        "        raise ValueError('price required')\n"
        "    return Decimal(value)\n"
    )

    initial = json.dumps(
        {
            "action": {
                "type": "write_file",
                "path": "models.py",
                "content": broken_source,
            }
        }
    )

    repair_prompts: list[str] = []

    def ask(prompt: str):
        repair_prompts.append(prompt)
        return json.dumps(
            {
                "action": {
                    "type": "write_file",
                    "path": "models.py",
                    "content": repaired_source,
                }
            }
        )

    result = run_adaptive_loop(
        initial_text=initial,
        original_request=(
            "Create models.py containing the requested inventory models."
        ),
        ask=ask,
        workspace=tmp_path,
        max_steps=5,
        progress=lambda _message: None,
    )

    assert repair_prompts

    prompt = repair_prompts[0]

    # Existing behavior already provides the target path and compiler
    # diagnostic. Real-world repair additionally requires the actual
    # malformed artifact so the provider can repair rather than regenerate.
    assert "models.py" in prompt
    assert "python syntax validation failed" in prompt.lower()

    assert (
        "DISTINCTIVE_REPAIR_CONTEXT = 'inventory-model-v1'"
        in prompt
    )

    assert (
        "def parse_price(value: str) -> Decimal:"
        in prompt
    )

    assert (
        "    if not value:\n"
        "    return Decimal(value)\n"
        in prompt
    )

    assert (tmp_path / "models.py").read_text(
        encoding="utf-8"
    ) == repaired_source

    assert "Execution stopped safely" not in result
