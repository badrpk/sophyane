from __future__ import annotations

import json
import os
from pathlib import Path

import sophyane.providers.nifdu_browser as nifdu


def test_provider_timeout_controls_bridge_import(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = tmp_path / "fake_bridge.py"

    module.write_text(
        (
            "import os\n"
            "TIMEOUT = int("
            "os.environ.get('SOPHYANE_CHATGPT_TIMEOUT', '300')"
            ")\n"
            "\n"
            "def ask(prompt, image=None):\n"
            "    return str(TIMEOUT)\n"
        ),
        encoding="utf-8",
    )

    selection = tmp_path / "selection.json"

    selection.write_text(
        json.dumps(
            {
                "kind": "function",
                "module": str(module),
                "name": "ask",
                "args": [
                    "prompt",
                    "image",
                ],
                "async": False,
                "score": 1,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv(
        "SOPHYANE_NIFDU_CALLABLE_FILE",
        str(selection),
    )

    monkeypatch.setenv(
        "SOPHYANE_CHATGPT_TIMEOUT",
        "300",
    )

    provider = nifdu.NifduBrowserProvider(
        timeout=17,
    )

    result = provider.generate(
        "hello"
    )

    assert result == "17"

    # Provider invocation must not permanently mutate the caller's
    # configured bridge timeout.
    assert (
        os.environ[
            "SOPHYANE_CHATGPT_TIMEOUT"
        ]
        == "300"
    )


def test_guarded_nifdu_calls_are_bounded() -> None:
    source = Path(
        "src/sophyane/nifdu_guarded_execution.py"
    ).read_text(
        encoding="utf-8",
    )

    assert source.count(
        "timeout=60,"
    ) >= 2


def test_guarded_prompts_isolate_stale_browser_context() -> None:
    source = Path(
        "src/sophyane/nifdu_guarded_execution.py"
    ).read_text(
        encoding="utf-8",
    )

    phrase = (
        "Treat this as a fresh isolated "
        "filesystem request."
    )

    assert source.count(
        phrase
    ) >= 2
