from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def clean_session_env(monkeypatch):
    for key in (
        "SOPHYANE_SESSION_MODE",
        "SOPHYANE_SESSION_PROVIDER",
        "SOPHYANE_SESSION_MODEL",
        "SOPHYANE_SESSION_TIMEOUT",
        "SOPHYANE_MODE4_EXTERNAL_FAILOVER",
    ):
        monkeypatch.delenv(
            key,
            raising=False,
        )


def test_human_conversation_create_provider_honors_explicit_nifdu_authority(
    monkeypatch,
):
    from sophyane.main import create_provider
    from sophyane.providers import nifdu_browser

    created = []

    class FakeNifduProvider:
        def __init__(
            self,
            *,
            model,
            timeout,
            **_kwargs,
        ):
            self.model = model
            self.timeout = timeout
            created.append(
                {
                    "model": model,
                    "timeout": timeout,
                }
            )

    monkeypatch.setattr(
        nifdu_browser,
        "NifduBrowserProvider",
        FakeNifduProvider,
    )

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
    monkeypatch.setenv(
        "SOPHYANE_SESSION_TIMEOUT",
        "30",
    )

    persisted = {
        "provider": "gemini",
        "model": "gemini-3.7-flash",
        "timeout": 600,
    }

    provider = create_provider(
        persisted
    )

    assert isinstance(
        provider,
        FakeNifduProvider,
    )
    assert provider.model == "chatgpt-browser"
    assert provider.timeout == 30
    assert created == [
        {
            "model": "chatgpt-browser",
            "timeout": 30,
        }
    ]


def test_human_conversation_authority_forbids_provider_switching(
    monkeypatch,
):
    from sophyane.intelligence_authority import (
        current_intelligence_authority,
    )

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

    authority = (
        current_intelligence_authority()
    )

    assert (
        authority.session_mode
        == "human_conversation"
    )
    assert (
        authority.session_provider
        == "nifdu_browser"
    )
    assert (
        authority.session_model
        == "chatgpt-browser"
    )
    assert (
        authority.provider_switching_allowed
        is False
    )


def test_human_conversation_persisted_provider_is_used_when_no_explicit_provider(
    monkeypatch,
):
    """
    Human Conversation is an interaction surface.

    When no transient provider override exists, it may inherit the configured
    provider; this test prevents the eventual fix from hardcoding NIFDU.
    """
    import sophyane.main as main

    captured = []

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "human_conversation",
    )

    monkeypatch.setattr(
        main,
        "PluginLoader",
        lambda: object(),
    )

    import sophyane.providers.fallback as fallback

    def fake_build(
        _loader,
        config,
    ):
        captured.append(
            dict(config)
        )
        return object()

    monkeypatch.setattr(
        fallback,
        "build_fallback_provider",
        fake_build,
    )

    configured = {
        "provider": "gemini",
        "model": "gemini-3.7-flash",
        "timeout": 600,
    }

    result = main.create_provider(
        configured
    )

    assert result is not None
    assert captured == [
        configured
    ]


def test_gemini_conversation_reply_uses_chat_response_mode():
    """conversation_reply must never be constrained by planner JSON schema."""
    from sophyane.providers.gemini import GeminiProvider

    prompt = (
        'SOPHYANE_DISCOVERY_REASONING_REQUEST\\n'
        '{"operation":"conversation_reply",'
        '"discovery_context":{"return_schema":{"reply":"string"}}}'
    )

    assert (
        GeminiProvider._response_mode(
            prompt,
            "Return one valid JSON object only.",
        )
        == "chat"
    )
