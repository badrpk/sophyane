from __future__ import annotations

import os

import pytest

import sophyane.cli_entry as cli_entry
import sophyane.startup_policy as startup_policy


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in (
        "SOPHYANE_SESSION_MODE",
        "SOPHYANE_SESSION_PROVIDER",
        "SOPHYANE_SESSION_MODEL",
        "SOPHYANE_SESSION_TIMEOUT",
        "SOPHYANE_SLI_GRAPH",
        "SOPHYANE_SLI_ONLY",
        "SOPHYANE_SLI_CONTINUOUS",
        "SOPHYANE_TOPIC_LEARNING",
        "SOPHYANE_LOCAL_ONLY",
        "SOPHYANE_DISABLE_CLOUD_FALLBACK",
    ):
        monkeypatch.delenv(key, raising=False)


def test_noninteractive_human_conversation_keeps_configured_provider(
    monkeypatch,
):
    config = {
        "provider": "nifdu_browser",
        "model": "chatgpt-browser",
        "company": "ChatGPT Browser",
        "timeout": 180,
    }

    monkeypatch.setattr(
        startup_policy,
        "load_config",
        lambda: dict(config),
    )
    monkeypatch.setattr(
        startup_policy,
        "_load_llm",
        lambda: {},
    )
    monkeypatch.setattr(
        startup_policy,
        "_local_candidate",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        startup_policy,
        "_configured_clouds",
        lambda: [],
    )
    monkeypatch.setattr(
        startup_policy.sys.stdin,
        "isatty",
        lambda: False,
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "human_conversation",
    )

    result = startup_policy.choose_startup_provider()

    assert result == config
    assert (
        os.environ["SOPHYANE_SESSION_MODE"]
        == "human_conversation"
    )


def test_human_conversation_does_not_force_model_bearing_identity(
    monkeypatch,
):
    config = {
        "provider": "nifdu_browser",
        "model": "configured-model",
        "company": "Configured",
        "timeout": 180,
    }

    monkeypatch.setattr(
        cli_entry,
        "load_config",
        lambda: dict(config),
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "human_conversation",
    )
    monkeypatch.delenv(
        "SOPHYANE_SESSION_MODEL",
        raising=False,
    )

    model = cli_entry._session_ready_model(
        config["model"]
    )

    assert model == "configured-model"


def test_human_conversation_preserves_explicit_session_model(
    monkeypatch,
):
    config = {
        "provider": "nifdu_browser",
        "model": "configured-model",
        "company": "Configured",
        "timeout": 180,
    }

    monkeypatch.setattr(
        cli_entry,
        "load_config",
        lambda: dict(config),
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "human_conversation",
    )
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODEL",
        "chatgpt-browser",
    )

    # Human Conversation is an interaction surface. It must not rewrite
    # explicit provider/model process authority.
    assert (
        os.environ["SOPHYANE_SESSION_MODEL"]
        == "chatgpt-browser"
    )


def test_human_conversation_with_local_config_can_start_local_server(
    monkeypatch,
):
    calls = []

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "human_conversation",
    )

    monkeypatch.setattr(
        cli_entry,
        "load_config",
        lambda: {
            "provider": "local_gguf",
            "model": "local-model",
        },
    )

    import sophyane.local_server as local_server

    monkeypatch.setattr(
        local_server,
        "ensure_server_background",
        lambda: calls.append(True) or (
            True,
            "test server ready",
        ),
    )

    cli_entry._start_local_server_if_needed()

    assert calls == [True]


def test_human_conversation_does_not_use_mode3_profile_server_path(
    monkeypatch,
):
    normal_calls = []
    profile_calls = []

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "human_conversation",
    )

    monkeypatch.setattr(
        cli_entry,
        "load_config",
        lambda: {
            "provider": "local_gguf",
            "model": "local-model",
        },
    )

    import sophyane.local_server as local_server
    import sophyane.local_model_profiles as profiles

    monkeypatch.setattr(
        local_server,
        "ensure_server_background",
        lambda: normal_calls.append(True) or (
            True,
            "normal local server",
        ),
    )
    monkeypatch.setattr(
        profiles,
        "ensure_profile_servers",
        lambda: profile_calls.append(True) or (
            True,
            "profile servers",
        ),
    )

    cli_entry._start_local_server_if_needed()

    assert normal_calls == [True]
    assert profile_calls == []
