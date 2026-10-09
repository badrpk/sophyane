from __future__ import annotations

import os

import pytest

from sophyane import startup_policy


def test_mode4_transport_families_are_exactly_three():
    families = startup_policy.mode4_transport_families()
    assert families == (
        "APIs",
        "NIFDU Browser",
        "Harnesses / CLI",
    )
    assert all("Local" not in family for family in families)


def test_mode4_api_choices_are_capped_and_preserve_configuration(monkeypatch):
    monkeypatch.setattr(
        startup_policy,
        "_configured_clouds",
        lambda: [(f"provider-{i}", f"Provider {i}") for i in range(12)],
    )
    monkeypatch.setattr(
        startup_policy,
        "_cloud_model",
        lambda provider, config, llm: f"{provider}-model",
    )

    choices = startup_policy.mode4_api_choices({}, {})
    assert len(choices) == 10
    assert choices[0] == ("provider-0", "Provider 0", "provider-0-model")


def test_mode4_harness_choices_require_real_adapters(monkeypatch):
    monkeypatch.setattr(startup_policy, "_mode4_codex_available", lambda: True)
    monkeypatch.setattr(startup_policy, "_mode4_agy_available", lambda: True)

    choices = startup_policy.mode4_harness_choices()
    by_id = {item[0]: item for item in choices}
    assert by_id["codex_cli"][0] == "codex_cli"
    assert by_id["codex_cli"][2] == "codex-default"
    assert by_id["agy"][0] == "agy"
    assert by_id["agy"][2] == "agy-default"
    assert "gemini" not in by_id
    assert "opencode" not in by_id
    assert len(choices) <= 10


def test_mode4_invalid_selection_does_not_change_authority(monkeypatch):
    monkeypatch.delenv("SOPHYANE_SESSION_MODE", raising=False)
    monkeypatch.delenv("SOPHYANE_SESSION_PROVIDER", raising=False)
    monkeypatch.delenv("SOPHYANE_SESSION_MODEL", raising=False)

    with pytest.raises(ValueError):
        startup_policy.apply_mode4_selection("invalid-family", "invalid-provider")

    assert "SOPHYANE_SESSION_MODE" not in os.environ
    assert "SOPHYANE_SESSION_PROVIDER" not in os.environ
    assert "SOPHYANE_SESSION_MODEL" not in os.environ


def test_mode4_nifdu_exposes_canonical_ten_browser_leafs(monkeypatch):
    import sophyane.startup_policy as startup_policy

    monkeypatch.setattr(
        startup_policy,
        "_mode4_nifdu_transport_available",
        lambda: True,
        raising=False,
    )

    choices = startup_policy.mode4_nifdu_choices()

    assert choices == [
        ("browser_chatgpt", "ChatGPT", "chatgpt-browser"),
        ("browser_claude", "Claude", "claude-browser"),
        ("browser_gemini", "Gemini", "gemini-browser"),
        ("browser_grok", "Grok", "grok-browser"),
        ("browser_perplexity", "Perplexity", "perplexity-browser"),
        ("browser_poe", "Poe", "poe-browser"),
        ("browser_copilot", "Copilot", "copilot-browser"),
        ("browser_mistral", "Mistral", "mistral-browser"),
        ("browser_qwen", "Qwen", "qwen-browser"),
        ("browser_kimi", "Kimi", "kimi-browser"),
    ]


def test_mode4_nifdu_leaf_preserves_sophyane_authority(monkeypatch):
    import os
    import sophyane.startup_policy as startup_policy

    monkeypatch.setattr(
        startup_policy,
        "_mode4_nifdu_transport_available",
        lambda: True,
        raising=False,
    )

    mode4_env_keys = (
        "SOPHYANE_NIFDU_PROVIDER",
        "SOPHYANE_NIFDU_SITE",
        "SOPHYANE_NIFDU_CALLABLE_FILE",
        "SOPHYANE_SESSION_MODE",
        "SOPHYANE_SESSION_PROVIDER",
        "SOPHYANE_SESSION_MODEL",
        "SOPHYANE_SESSION_TIMEOUT",
    )

    mode4_env_before = {
        key: os.environ.get(key)
        for key in mode4_env_keys
    }

    try:
        result = startup_policy.apply_mode4_selection(
            "NIFDU Browser",
            "browser_grok",
            "grok-browser",
            config={},
            llm={},
        )

        assert result == {
            "mode": "nifdu_llm",
            "provider": "nifdu_browser",
            "model": "grok-browser",
        }

        assert os.environ["SOPHYANE_SESSION_MODE"] == "nifdu_llm"
        assert os.environ["SOPHYANE_SESSION_PROVIDER"] == "nifdu_browser"
        assert os.environ["SOPHYANE_SESSION_MODEL"] == "grok-browser"
        assert os.environ["SOPHYANE_NIFDU_PROVIDER"] == "browser_grok"
        assert os.environ["SOPHYANE_NIFDU_SITE"] == "grok"
    finally:
        # apply_mode4_selection intentionally persists session state
        # through direct os.environ writes. Restore that state directly
        # so pytest's monkeypatch teardown cannot resurrect it.
        for key, previous in mode4_env_before.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous



def test_mode4_nifdu_unavailable_has_no_leaf_choices(monkeypatch):
    import sophyane.startup_policy as startup_policy

    monkeypatch.setattr(
        startup_policy,
        "_mode4_nifdu_transport_available",
        lambda: False,
        raising=False,
    )

    assert startup_policy.mode4_nifdu_choices() == []


def test_mode4_nifdu_leaf_adapter_uses_selected_site(monkeypatch):
    import os
    import sys
    import types

    from sophyane.providers import nifdu_leaf_adapter

    calls = []

    fake = types.ModuleType("_test_nifdu_multi_bridge")

    def ask(prompt, site):
        calls.append((prompt, site))
        return "leaf-result"

    fake.ask = ask

    monkeypatch.setattr(
        nifdu_leaf_adapter,
        "_load_external_bridge",
        lambda: fake,
    )
    monkeypatch.setenv("SOPHYANE_NIFDU_SITE", "grok")

    assert nifdu_leaf_adapter.ask("hello") == "leaf-result"
    assert calls == [("hello", "grok")]


def test_mode4_interactive_nifdu_returns_authority_not_leaf(monkeypatch):
    import os
    import sophyane.startup_policy as startup_policy

    monkeypatch.setattr(
        startup_policy,
        "mode4_nifdu_choices",
        lambda: [
            ("browser_chatgpt", "ChatGPT", "chatgpt-browser"),
            ("browser_grok", "Grok", "grok-browser"),
        ],
    )

    monkeypatch.setattr(
        startup_policy,
        "_configure_mode4_nifdu_leaf_callable",
        lambda: "/tmp/test-nifdu-leaf-callable.json",
    )

    answers = iter(["2", "2"])

    monkeypatch.setattr(
        "builtins.input",
        lambda prompt="": next(answers),
    )

    mode4_env_keys = (
        "SOPHYANE_NIFDU_PROVIDER",
        "SOPHYANE_NIFDU_SITE",
        "SOPHYANE_NIFDU_CALLABLE_FILE",
        "SOPHYANE_SESSION_MODE",
        "SOPHYANE_SESSION_PROVIDER",
        "SOPHYANE_SESSION_MODEL",
        "SOPHYANE_SESSION_TIMEOUT",
    )

    mode4_env_before = {
        key: os.environ.get(key)
        for key in mode4_env_keys
    }

    try:
        result = startup_policy._choose_mode4_transport({}, {})

        assert result["provider"] == "nifdu_browser"
        assert result["model"] == "grok-browser"
        assert result["company"] == "Grok"

        assert os.environ["SOPHYANE_SESSION_MODE"] == "nifdu_llm"
        assert os.environ["SOPHYANE_SESSION_PROVIDER"] == "nifdu_browser"
        assert os.environ["SOPHYANE_SESSION_MODEL"] == "grok-browser"
        assert os.environ["SOPHYANE_NIFDU_PROVIDER"] == "browser_grok"
        assert os.environ["SOPHYANE_NIFDU_SITE"] == "grok"
    finally:
        # Mode-4 selection intentionally persists process environment.
        # Restore direct production writes directly so this test cannot
        # contaminate later tests in the same pytest process.
        for key, previous in mode4_env_before.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous
