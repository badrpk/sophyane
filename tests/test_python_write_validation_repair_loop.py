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
