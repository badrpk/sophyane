from __future__ import annotations

from sophyane.main import (
    load_runtime_config,
)


def test_local_llm_session_overrides_persisted_runtime_config(
    monkeypatch,
):
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "local_llm",
    )

    import sophyane.main as main
    import sophyane.startup_policy as policy

    monkeypatch.setattr(
        main,
        "load_config",
        lambda: {
            "provider": "gemini",
            "model": "gemini-3.7-flash",
            "company": "Google Gemini",
            "timeout": 600,
        },
    )

    monkeypatch.setattr(
        policy,
        "choose_startup_provider",
        lambda: {
            "provider": "local_gguf",
            "model": "qwen2.5-1.5b-instruct-q4_k_m",
            "company": "Local",
            "timeout": 300,
        },
    )

    config = load_runtime_config()

    assert config["provider"] == "local_gguf"
    assert (
        config["model"]
        == "qwen2.5-1.5b-instruct-q4_k_m"
    )
    assert config["company"] == "Local"
    assert config["timeout"] == 300


def test_normal_session_preserves_persisted_config(
    monkeypatch,
):
    monkeypatch.delenv(
        "SOPHYANE_SESSION_MODE",
        raising=False,
    )

    import sophyane.main as main

    persisted = {
        "provider": "gemini",
        "model": "gemini-3.7-flash",
        "company": "Google Gemini",
        "timeout": 600,
    }

    monkeypatch.setattr(
        main,
        "load_config",
        lambda: dict(
            persisted
        ),
    )

    class Metadata:
        requires_api_key = False
        environment_variable = ""

    class Plugin:
        metadata = Metadata()

    class Loader:
        def discover(self):
            return {
                "gemini": Plugin(),
            }

    monkeypatch.setattr(
        main,
        "PluginLoader",
        Loader,
    )

    config = load_runtime_config()

    assert config == persisted
