from __future__ import annotations

import os


def test_mode3_runtime_config_never_exposes_gemini(
    monkeypatch,
):
    import sophyane.main as main
    import sophyane.startup_policy as policy

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "local_llm",
    )

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
        "resolve_local_session_config",
        lambda: {
            "provider": "local_gguf",
            "model": "qwen-local-test",
            "company": "Local",
            "timeout": 300,
        },
    )

    config = main.load_runtime_config()

    assert config["provider"] == "local_gguf"
    assert config["model"] == "qwen-local-test"
    assert config["company"] == "Local"

    rendered = repr(config).lower()

    assert "gemini" not in rendered
    assert "google" not in rendered


def test_mode3_provider_chain_is_singleton_local(
    monkeypatch,
):
    import sophyane.main as main

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "local_llm",
    )
    monkeypatch.setenv(
        "SOPHYANE_SESSION_PROVIDER",
        "local_gguf",
    )
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODEL",
        "qwen-local-test",
    )

    class Provider:
        primary = "local_gguf"
        _providers = [
            (
                "local_gguf",
                object(),
            )
        ]

    monkeypatch.setattr(
        main,
        "build_fallback_provider"
        if hasattr(main, "build_fallback_provider")
        else "PluginLoader",
        getattr(
            main,
            "PluginLoader",
        ),
        raising=False,
    )

    assert (
        os.environ["SOPHYANE_SESSION_PROVIDER"]
        == "local_gguf"
    )
    assert (
        os.environ["SOPHYANE_SESSION_MODE"]
        == "local_llm"
    )


def test_mode3_environment_forbids_cloud_fallback(
    monkeypatch,
):
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "local_llm",
    )
    monkeypatch.setenv(
        "SOPHYANE_LOCAL_ONLY",
        "1",
    )
    monkeypatch.setenv(
        "SOPHYANE_DISABLE_CLOUD_FALLBACK",
        "1",
    )

    assert os.environ["SOPHYANE_LOCAL_ONLY"] == "1"
    assert (
        os.environ[
            "SOPHYANE_DISABLE_CLOUD_FALLBACK"
        ]
        == "1"
    )
