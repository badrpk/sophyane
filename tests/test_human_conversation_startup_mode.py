from __future__ import annotations

import builtins
import os

import pytest

import sophyane.startup_policy as startup_policy


CLEAR_FLAGS = (
    "SOPHYANE_SLI_GRAPH",
    "SOPHYANE_SLI_ONLY",
    "SOPHYANE_SLI_CONTINUOUS",
    "SOPHYANE_TOPIC_LEARNING",
    "SOPHYANE_LOCAL_ONLY",
    "SOPHYANE_DISABLE_CLOUD_FALLBACK",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    keys = (
        "SOPHYANE_SESSION_MODE",
        "SOPHYANE_SESSION_PROVIDER",
        "SOPHYANE_SESSION_MODEL",
        "SOPHYANE_SESSION_TIMEOUT",
        *CLEAR_FLAGS,
    )

    for key in keys:
        monkeypatch.delenv(
            key,
            raising=False,
        )


def _select_six(monkeypatch):
    config = {
        "provider": "local_gguf",
        "model": "existing-model",
        "company": "Local",
        "timeout": 60,
    }

    monkeypatch.setattr(
        startup_policy.sys.stdin,
        "isatty",
        lambda: True,
    )
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
        lambda *_args, **_kwargs: (
            "local_gguf",
            "existing-model",
        ),
    )
    monkeypatch.setattr(
        startup_policy,
        "_configured_clouds",
        lambda: [],
    )
    monkeypatch.setattr(
        startup_policy,
        "_verbose_startup_enabled",
        lambda: False,
    )

    import shutil
    import sophyane.providers.codex_cli as codex_provider

    monkeypatch.setattr(
        shutil,
        "which",
        lambda _name: None,
    )
    monkeypatch.setattr(
        codex_provider,
        "agy_available",
        lambda: False,
    )

    answers = iter(("6", "1"))

    monkeypatch.setattr(
        builtins,
        "input",
        lambda _prompt="": next(answers),
    )

    writes = []

    if hasattr(
        startup_policy,
        "save_config",
    ):
        monkeypatch.setattr(
            startup_policy,
            "save_config",
            lambda value: writes.append(
                (
                    "config",
                    value,
                )
            ),
        )

    if hasattr(
        startup_policy,
        "save_json",
    ):
        monkeypatch.setattr(
            startup_policy,
            "save_json",
            lambda *args, **kwargs: writes.append(
                (
                    "json",
                    args,
                    kwargs,
                )
            ),
        )

    result = (
        startup_policy.choose_startup_provider()
    )

    return config, result, writes


def test_six_selects_human_conversation(
    monkeypatch,
):
    _select_six(
        monkeypatch
    )

    assert (
        os.environ.get(
            "SOPHYANE_SESSION_MODE"
        )
        == "human_conversation"
    )


def test_six_clears_incompatible_flags(
    monkeypatch,
):
    for key in CLEAR_FLAGS:
        monkeypatch.setenv(
            key,
            "1",
        )

    _select_six(
        monkeypatch
    )

    for key in CLEAR_FLAGS:
        assert (
            os.environ.get(
                key
            )
            is None
        )


def test_six_preserves_provider_authority(
    monkeypatch,
):
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
        "180",
    )

    _select_six(
        monkeypatch
    )

    assert (
        os.environ[
            "SOPHYANE_SESSION_PROVIDER"
        ]
        == "nifdu_browser"
    )
    assert (
        os.environ[
            "SOPHYANE_SESSION_MODEL"
        ]
        == "chatgpt-browser"
    )
    assert (
        os.environ[
            "SOPHYANE_SESSION_TIMEOUT"
        ]
        == "180"
    )


def test_six_does_not_persist_provider(
    monkeypatch,
):
    config, result, writes = (
        _select_six(
            monkeypatch
        )
    )

    assert result == config
    assert writes == []


def test_noninteractive_human_mode_preserved(
    monkeypatch,
):
    config = {
        "provider": "local_gguf",
        "model": "existing-model",
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

    result = (
        startup_policy.choose_startup_provider()
    )

    assert result == config
    assert (
        os.environ[
            "SOPHYANE_SESSION_MODE"
        ]
        == "human_conversation"
    )
