from __future__ import annotations

import json
from pathlib import Path

import sophyane.adaptive_execution as adaptive


def test_full_stack_contract_marks_bundle_first() -> None:
    source = Path(
        "src/sophyane/adaptive_execution.py"
    ).read_text(
        encoding="utf-8",
    )

    assert "SOPHYANE_FULL_STACK_BUNDLE_FIRST_V1" in source
    assert "SOPHYANE_FULL_STACK_BUNDLE_VERIFY_V1" in source


def test_context_decomposition_materializes_files_incrementally(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    responses = iter(
        (
            json.dumps(
                {
                    "action": {
                        "type": "write_file",
                        "path": "backend/app.py",
                        "content": "print('backend')\n",
                    }
                }
            ),
            json.dumps(
                {
                    "action": {
                        "type": "write_file",
                        "path": "static/index.html",
                        "content": (
                            "<!doctype html>"
                            "<html><head>"
                            "<meta name='viewport' "
                            "content='width=device-width,initial-scale=1'>"
                            "</head><body>ok</body></html>"
                        ),
                    }
                }
            ),
            json.dumps(
                {
                    "action": {
                        "type": "write_file",
                        "path": "static/app.js",
                        "content": "fetch('/api/tasks');\n",
                    }
                }
            ),
            json.dumps(
                {
                    "action": {
                        "type": "write_file",
                        "path": "static/style.css",
                        "content": "body{font-family:sans-serif}\n",
                    }
                }
            ),
            json.dumps(
                {
                    "action": {
                        "type": "write_file",
                        "path": "tests/test_app.py",
                        "content": (
                            "def test_smoke():\n"
                            "    assert True\n"
                        ),
                    }
                }
            ),
            json.dumps(
                {
                    "action": {
                        "type": "write_file",
                        "path": "README.md",
                        "content": "# demo\n",
                    }
                }
            ),
        )
    )

    def ask(prompt: str):
        calls.append(prompt)

        try:
            return next(
                responses
            )

        except StopIteration:
            # The six deterministic artifact increments are the subject
            # of this test. After they are materialized, adaptive_execution
            # may legitimately enter deterministic verification or targeted
            # repair. Keep the fake provider bounded instead of leaking
            # StopIteration out of the fixture.
            return json.dumps(
                {
                    "action": {
                        "type": "respond",
                        "message": "fixture complete",
                    }
                }
            )

    adaptive.run_adaptive_loop(
        initial_text=json.dumps(
            {
                "action": {
                    "type": "respond",
                    "message": "planning output",
                }
            }
        ),
        original_request=(
            "Build a complete local SaaS.\n"
            "=== SOPHYANE FULL-STACK ARCHITECTURE CONTRACT ===\n"
            "Python sqlite3 persistent storage.\n"
            "REST-style JSON endpoints.\n"
            "HTML/CSS/vanilla JavaScript frontend.\n"
            "=== END FULL-STACK ARCHITECTURE CONTRACT ==="
        ),
        ask=ask,
        workspace=tmp_path,
        max_steps=16,
        progress=lambda _message: None,
    )

    assert (
        tmp_path
        / "backend/app.py"
    ).is_file()

    assert (
        tmp_path
        / "static/index.html"
    ).is_file()

    assert (
        tmp_path
        / "static/app.js"
    ).is_file()

    assert (
        tmp_path
        / "static/style.css"
    ).is_file()

    assert (
        tmp_path
        / "tests/test_app.py"
    ).is_file()

    assert (
        tmp_path
        / "README.md"
    ).is_file()

    assert calls

    assert (
        "full-stack implementation increment 1"
        in calls[0].lower()
    )

    assert any(
        "static/index.html only"
        in prompt.lower()
        for prompt in calls[1:]
    )

    assert any(
        "static/app.js only"
        in prompt.lower()
        for prompt in calls[1:]
    )

    assert any(
        "static/style.css only"
        in prompt.lower()
        for prompt in calls[1:]
    )

    assert any(
        "tests/test_app.py only"
        in prompt.lower()
        for prompt in calls[1:]
    )

    assert any(
        "readme.md only"
        in prompt.lower()
        for prompt in calls[1:]
    )




def test_incremental_python_syntax_is_still_guarded(
    tmp_path: Path,
) -> None:
    prompts: list[str] = []

    responses = iter(
        (
            json.dumps(
                {
                    "action": {
                        "type": "write_file",
                        "path": "backend/app.py",
                        "content": (
                            "print('broken\n"
                            "')\n"
                        ),
                    }
                }
            ),
            json.dumps(
                {
                    "action": {
                        "type": "write_file",
                        "path": "backend/app.py",
                        "content": "print('repaired')\n",
                    }
                }
            ),
        )
    )

    def ask(prompt: str):
        prompts.append(prompt)

        try:
            return next(
                responses
            )
        except StopIteration:
            return json.dumps(
                {
                    "action": {
                        "type": "respond",
                        "message": "stop",
                    }
                }
            )

    adaptive.run_adaptive_loop(
        initial_text=json.dumps(
            {
                "action": {
                    "type": "respond",
                    "message": "planning output",
                }
            }
        ),
        original_request=(
            "Build a full-stack local software product.\n"
            "=== SOPHYANE FULL-STACK ARCHITECTURE CONTRACT ===\n"
            "Python sqlite3 + REST API.\n"
            "=== END FULL-STACK ARCHITECTURE CONTRACT ==="
        ),
        ask=ask,
        workspace=tmp_path,
        max_steps=8,
        progress=lambda _message: None,
    )

    assert len(
        prompts
    ) >= 2

    assert (
        "full-stack implementation increment 1"
        in prompts[0].lower()
    )

    assert (
        "python syntax validation failed"
        in prompts[1].lower()
        or "repair"
        in prompts[1].lower()
    )
