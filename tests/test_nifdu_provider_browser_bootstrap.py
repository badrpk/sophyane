from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import sophyane.browser as browser
import sophyane.providers.nifdu_browser as nifdu
from sophyane.providers.base import ProviderError


def _fake_bridge_module(
    response: str = "bridge-ok",
):
    return SimpleNamespace(
        ask=lambda prompt, image=None: response
    )


def test_default_provider_bootstraps_browser_before_bridge(
    monkeypatch,
) -> None:
    events: list[str] = []

    monkeypatch.delenv(
        "SOPHYANE_NIFDU_CALLABLE_FILE",
        raising=False,
    )

    def fake_launch():
        events.append(
            "browser"
        )

        return {
            "ok": True,
            "launched": True,
            "reused": False,
            "pid": 12345,
        }

    def fake_load_module(
        path: Path,
    ):
        events.append(
            "module"
        )

        assert (
            path.resolve()
            == nifdu._tracked_bridge_path()
        )

        return _fake_bridge_module()

    monkeypatch.setattr(
        browser,
        "launch_nifdu_browser",
        fake_launch,
    )

    monkeypatch.setattr(
        nifdu,
        "_load_module",
        fake_load_module,
    )

    provider = (
        nifdu.NifduBrowserProvider(
            timeout=17,
        )
    )

    result = provider.generate(
        "hello"
    )

    assert result == "bridge-ok"

    assert events == [
        "browser",
        "module",
    ]


def test_default_provider_accepts_reused_browser(
    monkeypatch,
) -> None:
    monkeypatch.delenv(
        "SOPHYANE_NIFDU_CALLABLE_FILE",
        raising=False,
    )

    calls = {
        "browser": 0,
    }

    def fake_launch():
        calls["browser"] += 1

        return {
            "ok": True,
            "launched": False,
            "reused": True,
            "pid": None,
        }

    monkeypatch.setattr(
        browser,
        "launch_nifdu_browser",
        fake_launch,
    )

    monkeypatch.setattr(
        nifdu,
        "_load_module",
        lambda path: _fake_bridge_module(
            "reused-ok"
        ),
    )

    provider = (
        nifdu.NifduBrowserProvider()
    )

    assert (
        provider.generate(
            "hello"
        )
        == "reused-ok"
    )

    assert calls["browser"] == 1


def test_default_provider_fails_closed_when_browser_bootstrap_fails(
    monkeypatch,
) -> None:
    monkeypatch.delenv(
        "SOPHYANE_NIFDU_CALLABLE_FILE",
        raising=False,
    )

    module_loaded = False

    def fake_launch():
        return {
            "ok": False,
            "launched": False,
            "reused": False,
            "pid": None,
            "error": "chromium unavailable",
        }

    def forbidden_load_module(
        path: Path,
    ):
        nonlocal module_loaded
        module_loaded = True

        raise AssertionError(
            "bridge must not load after bootstrap failure"
        )

    monkeypatch.setattr(
        browser,
        "launch_nifdu_browser",
        fake_launch,
    )

    monkeypatch.setattr(
        nifdu,
        "_load_module",
        forbidden_load_module,
    )

    provider = (
        nifdu.NifduBrowserProvider()
    )

    with pytest.raises(
        ProviderError,
        match=(
            "NIFDU browser bootstrap failed: "
            "chromium unavailable"
        ),
    ):
        provider.generate(
            "hello"
        )

    assert module_loaded is False


def test_explicit_external_selection_never_bootstraps_browser(
    monkeypatch,
    tmp_path: Path,
) -> None:
    bridge = (
        tmp_path
        / "external_bridge.py"
    )

    bridge.write_text(
        (
            "def ask(prompt, image=None):\n"
            "    return 'external-ok'\n"
        ),
        encoding="utf-8",
    )

    selection = (
        tmp_path
        / "selection.json"
    )

    selection.write_text(
        json.dumps(
            {
                "kind": "function",
                "module": str(
                    bridge
                ),
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

    def forbidden_launch():
        raise AssertionError(
            "explicit selection must not "
            "bootstrap tracked Chromium"
        )

    monkeypatch.setattr(
        browser,
        "launch_nifdu_browser",
        forbidden_launch,
    )

    provider = (
        nifdu.NifduBrowserProvider(
            timeout=5,
        )
    )

    assert (
        provider.generate(
            "hello"
        )
        == "external-ok"
    )


def test_external_missing_selection_fails_before_browser_bootstrap(
    monkeypatch,
    tmp_path: Path,
) -> None:
    missing = (
        tmp_path
        / "missing.json"
    )

    monkeypatch.setenv(
        "SOPHYANE_NIFDU_CALLABLE_FILE",
        str(missing),
    )

    def forbidden_launch():
        raise AssertionError(
            "missing explicit selection must "
            "not bootstrap Chromium"
        )

    monkeypatch.setattr(
        browser,
        "launch_nifdu_browser",
        forbidden_launch,
    )

    provider = (
        nifdu.NifduBrowserProvider()
    )

    with pytest.raises(
        ProviderError,
        match="callable selection is missing",
    ):
        provider.generate(
            "hello"
        )


def test_provider_source_contains_bootstrap_authority_marker():
    source = Path(
        "src/sophyane/providers/nifdu_browser.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        "SOPHYANE_NIFDU_PROVIDER_BROWSER_BOOTSTRAP_AUTHORITY_V1"
        in source
    )

    assert (
        "launch_nifdu_browser"
        in source
    )

    assert (
        "NIFDU browser bootstrap failed"
        in source
    )
