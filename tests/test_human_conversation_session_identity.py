import os

import pytest


def test_human_conversation_runtime_identity_uses_explicit_session_model(
    monkeypatch,
):
    from sophyane import cli_entry

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "human_conversation",
    )
    monkeypatch.setenv(
        "SOPHYANE_SESSION_PROVIDER",
        "nifdu_browser",
    )
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODEL",
        "chatgpt-browser",
    )

    identity = cli_entry._runtime_identity()

    assert "chatgpt-browser" in identity
    assert "gemini" not in identity.casefold()


def test_human_conversation_explicit_codex_provider_is_authoritative(
    monkeypatch,
):
    import sophyane.main as main

    class FakeCodexProvider:
        def __init__(
            self,
            model=None,
            timeout=None,
            **kwargs,
        ):
            self.model = model
            self.timeout = timeout
            self.kwargs = kwargs

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "human_conversation",
    )
    monkeypatch.setenv(
        "SOPHYANE_SESSION_PROVIDER",
        "codex_cli",
    )
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODEL",
        "gpt-test",
    )
    monkeypatch.setenv(
        "SOPHYANE_SESSION_TIMEOUT",
        "77",
    )

    monkeypatch.setattr(
        "sophyane.providers.codex_cli.CodexCliProvider",
        FakeCodexProvider,
    )

    provider = main.create_provider(
        {
            "provider": "gemini",
            "model": "gemini-3.7-flash",
            "timeout": 600,
        }
    )

    assert isinstance(
        provider,
        FakeCodexProvider,
    )
    assert provider.model == "gpt-test"
    assert provider.timeout == 77


def test_human_conversation_without_explicit_provider_keeps_persisted_provider(
    monkeypatch,
):
    import sophyane.main as main

    captured = {}

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "human_conversation",
    )

    monkeypatch.delenv(
        "SOPHYANE_SESSION_PROVIDER",
        raising=False,
    )
    monkeypatch.delenv(
        "SOPHYANE_SESSION_MODEL",
        raising=False,
    )
    monkeypatch.delenv(
        "SOPHYANE_SESSION_TIMEOUT",
        raising=False,
    )

    class FakeLoader:
        pass

    monkeypatch.setattr(
        main,
        "PluginLoader",
        FakeLoader,
    )

    def fake_builder(loader, config):
        captured["loader"] = loader
        captured["config"] = dict(config)
        return object()

    monkeypatch.setattr(
        "sophyane.providers.fallback.build_fallback_provider",
        fake_builder,
    )

    original = {
        "provider": "gemini",
        "model": "gemini-3.7-flash",
        "timeout": 600,
    }

    main.create_provider(original)

    assert captured["config"] == original
