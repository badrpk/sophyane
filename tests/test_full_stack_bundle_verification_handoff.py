from __future__ import annotations

import json
from pathlib import Path

import sophyane.adaptive_execution as adaptive


def _bundle() -> str:
    return json.dumps(
        {
            "files": [
                {
                    "path": "backend/app.py",
                    "content": (
                        "print('backend')\n"
                    ),
                },
                {
                    "path": "static/index.html",
                    "content": (
                        "<!doctype html>"
                        "<html><head>"
                        "<meta name='viewport' "
                        "content='width=device-width,initial-scale=1'>"
                        "</head><body>demo</body></html>"
                    ),
                },
                {
                    "path": "tests/test_smoke.py",
                    "content": (
                        "def test_smoke():\n"
                        "    assert True\n"
                    ),
                },
            ]
        }
    )


def test_json_bundle_enters_deterministic_verification(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    events: list[str] = []

    def ask(prompt: str):
        calls.append(prompt)

        # Dedicated full-stack implementation call.
        if len(calls) == 1:
            return _bundle()

        # If the runtime eventually needs a provider after local verification,
        # stop cleanly. The critical assertion is that deterministic work
        # happens before this second call.
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
                    "type": "respond",
                    "message": "planning output",
                }
            }
        ),
        original_request=(
            "Build a full-stack SaaS.\n"
            "=== SOPHYANE FULL-STACK ARCHITECTURE CONTRACT ===\n"
            "Python sqlite3 persistent storage.\n"
            "REST-style JSON endpoints.\n"
            "HTML/CSS/vanilla JavaScript frontend.\n"
            "Automated tests.\n"
            "=== END FULL-STACK ARCHITECTURE CONTRACT ==="
        ),
        ask=ask,
        workspace=tmp_path,
        max_steps=8,
        progress=events.append,
    )

    assert (
        tmp_path / "backend/app.py"
    ).is_file()

    assert (
        tmp_path / "static/index.html"
    ).is_file()

    assert (
        tmp_path / "tests/test_smoke.py"
    ).is_file()

    joined = "\n".join(events).lower()

    assert (
        "initial multi-file bundle materialized"
        in joined
    )

    assert (
        "deterministic verification owns next steps"
        in joined
    )


def test_verification_handoff_does_not_depend_on_markdown_flag() -> None:
    source = Path(
        "src/sophyane/adaptive_execution.py"
    ).read_text(
        encoding="utf-8",
    )

    marker = (
        "SOPHYANE_JSON_BUNDLE_VERIFICATION_HANDOFF_V1"
    )

    assert marker in source

    tail = source[
        source.index(marker):
        source.index(marker) + 1800
    ]

    assert (
        "and markdown_bundle_written"
        not in tail
    )

    assert (
        "initial_bundle_materialized"
        in tail
    )


def test_single_file_batch_does_not_claim_initial_project_bundle(
    tmp_path: Path,
) -> None:
    events: list[str] = []

    # This request intentionally does not activate the full-stack contract.
    adaptive.run_adaptive_loop(
        initial_text=json.dumps(
            {
                "files": [
                    {
                        "path": "hello.py",
                        "content": "print('hello')\n",
                    }
                ]
            }
        ),
        original_request=(
            "Create hello.py."
        ),
        ask=lambda _prompt: json.dumps(
            {
                "action": {
                    "type": "respond",
                    "message": "done",
                }
            }
        ),
        workspace=tmp_path,
        max_steps=4,
        progress=events.append,
    )

    assert (
        tmp_path / "hello.py"
    ).is_file()

    joined = "\n".join(events).lower()

    assert (
        "initial multi-file bundle materialized"
        not in joined
    )
