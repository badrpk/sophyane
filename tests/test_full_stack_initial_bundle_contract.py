from __future__ import annotations

import json
from pathlib import Path

import sophyane.adaptive_execution as adaptive


def test_create_file_string_action_is_write_file() -> None:
    value = {
        "action": "create_file",
        "path": "app.py",
        "content": "print('ok')\n",
    }

    result = adaptive._normalise_action(value)

    assert result is not None
    assert result["type"] == "write_file"
    assert result["path"] == "app.py"
    assert "action" not in result


def test_initial_bundle_prompt_demands_multifile_project() -> None:
    prompt = adaptive._full_stack_initial_bundle_prompt(
        "Build a project-management SaaS."
    ).lower()

    assert "top-level files array" in prompt
    assert "backend/app.py" in prompt
    assert "static/index.html" in prompt
    assert "static/app.js" in prompt
    assert "static/style.css" in prompt
    assert "tests/test_app.py" in prompt
    assert "sqlite3" in prompt
    assert "threadinghttpserver" in prompt
    assert "get /api/projects" in prompt
    assert "post /api/tasks" in prompt
    assert "put /api/tasks/{id}" in prompt
    assert "delete /api/tasks/{id}" in prompt
    assert "fetch()" in prompt


def test_full_stack_runtime_requests_bundle_before_actions(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    bundle = json.dumps(
        {
            "files": [
                {
                    "path": "backend/app.py",
                    "content": "print('backend')\n",
                },
                {
                    "path": "static/index.html",
                    "content": (
                        "<!doctype html>"
                        "<html><head>"
                        "<meta name='viewport' "
                        "content='width=device-width,initial-scale=1'>"
                        "</head><body>ok</body></html>"
                    ),
                },
                {
                    "path": "static/app.js",
                    "content": "fetch('/api/tasks');\n",
                },
                {
                    "path": "static/style.css",
                    "content": "body{font-family:sans-serif}\n",
                },
                {
                    "path": "tests/test_app.py",
                    "content": (
                        "def test_smoke():\n"
                        "    assert True\n"
                    ),
                },
                {
                    "path": "README.md",
                    "content": "# demo\n",
                },
            ]
        }
    )

    def ask(prompt: str):
        calls.append(prompt)

        if len(calls) == 1:
            return bundle

        return json.dumps(
            {
                "action": {
                    "type": "respond",
                    "message": "done",
                }
            }
        )

    adaptive.run_adaptive_loop(
        initial_text=json.dumps(
            {
                "action": {
                    "type": "write_file",
                    "path": "tiny.html",
                    "content": "<html></html>",
                }
            }
        ),
        original_request=(
            "Build a SaaS.\n"
            "=== SOPHYANE FULL-STACK ARCHITECTURE CONTRACT ===\n"
            "Python sqlite3 persistent storage and REST API.\n"
            "=== END FULL-STACK ARCHITECTURE CONTRACT ==="
        ),
        ask=ask,
        workspace=tmp_path,
        max_steps=8,
        progress=lambda _message: None,
    )

    assert calls

    assert (
        "full-stack initial implementation bundle"
        in calls[0].lower()
    )

    assert (
        tmp_path / "backend/app.py"
    ).is_file()

    assert (
        tmp_path / "static/index.html"
    ).is_file()

    assert not (
        tmp_path / "tiny.html"
    ).exists()


def test_normal_non_full_stack_does_not_force_bundle(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def ask(prompt: str):
        calls.append(prompt)

        return json.dumps(
            {
                "action": {
                    "type": "respond",
                    "message": "done",
                }
            }
        )

    adaptive.run_adaptive_loop(
        initial_text=json.dumps(
            {
                "action": {
                    "type": "write_file",
                    "path": "hello.py",
                    "content": "print('hello')\n",
                }
            }
        ),
        original_request=(
            "Create hello.py."
        ),
        ask=ask,
        workspace=tmp_path,
        max_steps=4,
        progress=lambda _message: None,
    )

    assert (
        tmp_path / "hello.py"
    ).is_file()

    assert not any(
        "full-stack initial implementation bundle"
        in prompt.lower()
        for prompt in calls
    )
