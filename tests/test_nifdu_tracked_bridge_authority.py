from __future__ import annotations

import json
from pathlib import Path


def test_tracked_bridge_is_packaged_python_source() -> None:
    from sophyane.providers.nifdu_browser import (
        _tracked_bridge_path,
    )

    bridge = _tracked_bridge_path()

    assert bridge.is_file()

    assert (
        bridge.name
        == "nifdu_cdp_bridge.py"
    )

    assert (
        "src/sophyane/providers"
        in str(bridge).replace("\\", "/")
    )


def test_tracked_bridge_contains_identical_response_fix() -> None:
    bridge = Path(
        "src/sophyane/providers/nifdu_cdp_bridge.py"
    )

    source = bridge.read_text(
        encoding="utf-8",
    )

    assert (
        "SOPHYANE_CDP_IDENTICAL_RESPONSE_FRESHNESS_V1"
        in source
    )

    assert (
        "user_count"
        in source
    )

    assert (
        "streaming_seen"
        in source
    )

    assert (
        "new_user_turn_seen"
        in source
    )


def test_default_provider_selection_uses_tracked_bridge(
    monkeypatch,
) -> None:
    import sophyane.providers.nifdu_browser as nifdu

    monkeypatch.delenv(
        "SOPHYANE_NIFDU_CALLABLE_FILE",
        raising=False,
    )

    selection = (
        nifdu._default_selection()
    )

    assert (
        selection["module"]
        == str(
            nifdu._tracked_bridge_path()
        )
    )

    assert selection["name"] == "ask"

    assert selection["args"] == [
        "prompt",
        "image",
    ]


def test_explicit_external_selection_remains_supported(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import sophyane.providers.nifdu_browser as nifdu

    bridge = tmp_path / "external_bridge.py"

    bridge.write_text(
        (
            "def ask(prompt, image=None):\n"
            "    return 'external-ok'\n"
        ),
        encoding="utf-8",
    )

    selection = tmp_path / "selection.json"

    selection.write_text(
        json.dumps(
            {
                "kind": "function",
                "module": str(bridge),
                "name": "ask",
                "args": [
                    "prompt",
                    "image",
                ],
                "async": False,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv(
        "SOPHYANE_NIFDU_CALLABLE_FILE",
        str(selection),
    )

    provider = nifdu.NifduBrowserProvider(
        timeout=5,
    )

    assert (
        provider.generate(
            "hello"
        )
        == "external-ok"
    )


def test_tracked_bridge_supports_current_chatgpt_message_dom():
    from pathlib import Path

    source = Path(
        "src/sophyane/providers/nifdu_cdp_bridge.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        "SOPHYANE_CDP_CURRENT_CHATGPT_MESSAGE_DOM_V1"
        in source
    )

    # Historical contract remains supported.
    assert (
        '[data-message-author-role="assistant"]'
        in source
    )

    assert (
        '[data-message-author-role="user"]'
        in source
    )

    # Current ChatGPT conversation shell.
    assert (
        'ol[aria-label="Conversation"]'
        in source
    )

    assert (
        'assistantMessage'
        in source
    )

    assert (
        'userMessageGroup'
        in source
    )

    assert (
        'userMessage'
        in source
    )

    # Streaming completion detection must remain present.
    assert (
        '[data-testid="stop-button"]'
        in source
    )
