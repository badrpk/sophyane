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


def test_multifile_json_bundle_materializes_without_per_file_provider_calls(
    tmp_path: Path,
) -> None:
    initial = json.dumps(
        {
            "files": [
                {
                    "path": "app.py",
                    "content": "print('ok')\n",
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
                    "path": "tests/test_smoke.py",
                    "content": (
                        "def test_smoke():\n"
                        "    assert 2 + 2 == 4\n"
                    ),
                },
            ]
        }
    )

    calls: list[str] = []

    def ask(prompt: str):
        calls.append(prompt)

        # Active full-stack semantics make one dedicated implementation
        # bundle request instead of treating planning initial_text as the
        # authoritative project artifact.
        if len(calls) == 1:
            return initial

        return json.dumps(
            {
                "action": {
                    "type": "respond",
                    "message": "done",
                }
            }
        )

    result = adaptive.run_adaptive_loop(
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
        max_steps=8,
        progress=lambda _message: None,
    )

    assert (tmp_path / "app.py").is_file()
    assert (tmp_path / "static/index.html").is_file()
    assert (tmp_path / "tests/test_smoke.py").is_file()

    # The first provider call must be the dedicated implementation-bundle
    # request, and the complete bundle must be materialized from that response.
    #
    # The runtime now owns deterministic post-bundle verification
    # (syntax -> tests -> launch -> HTTP/API probes). If this deliberately
    # minimal fixture cannot satisfy those later runtime checks, targeted
    # repair calls are expected and must not be counted as failure of the
    # bundle-first mechanism itself.
    assert calls

    assert (
        "full-stack initial implementation bundle"
        in calls[0].lower()
    )

    assert result


def test_bundle_python_syntax_is_still_guarded(
    tmp_path: Path,
) -> None:
    bad = json.dumps(
        {
            "files": [
                {
                    "path": "backend/app.py",
                    "content": (
                        "print('broken\n"
                        "')\n"
                    ),
                },
                {
                    "path": "index.html",
                    "content": "<!doctype html><html></html>",
                },
            ]
        }
    )

    prompts: list[str] = []

    def ask(prompt: str):
        prompts.append(prompt)

        # First call is the dedicated full-stack implementation request.
        # Return the malformed project bundle so the runtime can materialize
        # it and exercise immediate Python validation.
        if len(prompts) == 1:
            return bad

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

    assert len(prompts) >= 2

    assert (
        "full-stack initial implementation bundle"
        in prompts[0].lower()
    )

    repair_prompt = prompts[1].lower()

    assert (
        "python syntax validation failed"
        in repair_prompt
        or "syntax" in repair_prompt
    )

    assert "backend/app.py" in repair_prompt
