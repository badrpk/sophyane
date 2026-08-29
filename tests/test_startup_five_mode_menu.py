from __future__ import annotations
import os
import pytest


import io
from contextlib import (
    redirect_stderr,
    redirect_stdout,
)

import sophyane.startup_policy as policy


STARTUP_SESSION_KEYS = (
    "SOPHYANE_SESSION_MODE",
    "SOPHYANE_SLI_GRAPH",
    "SOPHYANE_SLI_ONLY",
    "SOPHYANE_SLI_CONTINUOUS",
    "SOPHYANE_TOPIC_LEARNING",
    "SOPHYANE_LOCAL_ONLY",
    "SOPHYANE_DISABLE_CLOUD_FALLBACK",
    "SOPHYANE_DISABLE_LOCAL_FALLBACK",
    "SOPHYANE_ALLOW_CLOUD_LOCAL_RESCUE",
    "SOPHYANE_SESSION_PROVIDER",
    "SOPHYANE_SESSION_MODEL",
    "SOPHYANE_SESSION_TIMEOUT",
)


@pytest.fixture(autouse=True)
def clean_startup_session_environment():
    """Keep startup-mode tests isolated inside one pytest process."""

    for key in STARTUP_SESSION_KEYS:
        os.environ.pop(
            key,
            None,
        )

    yield

    for key in STARTUP_SESSION_KEYS:
        os.environ.pop(
            key,
            None,
        )


def _interactive(monkeypatch):
    monkeypatch.setattr(
        policy.sys.stdin,
        "isatty",
        lambda: True,
    )


def _common(monkeypatch):
    monkeypatch.setattr(
        policy,
        "load_config",
        lambda: {},
    )

    monkeypatch.setattr(
        policy,
        "_load_llm",
        lambda: {},
    )

    monkeypatch.setattr(
        policy,
        "save_config",
        lambda config: None,
    )

    monkeypatch.setattr(
        policy,
        "save_json",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(
        policy,
        "_verbose_startup_enabled",
        lambda: False,
    )

    _interactive(monkeypatch)


def test_local_only_shows_all_five_modes(
    monkeypatch,
):
    _common(monkeypatch)

    monkeypatch.setattr(
        policy,
        "_local_candidate",
        lambda config, llm: (
            "local_gguf",
            "test-local-model",
        ),
    )

    monkeypatch.setattr(
        policy,
        "_configured_clouds",
        lambda: [],
    )

    monkeypatch.setattr(
        "builtins.input",
        lambda prompt="": "",
    )

    stderr = io.StringIO()

    with redirect_stderr(stderr):
        result = policy.choose_startup_provider()

    output = stderr.getvalue()

    assert result == {}

    assert "1. Sophyane" in output
    assert "2. SLI Graph" in output
    assert "3. Local LLM" in output
    assert "4. Cloud LLM" in output
    assert "5. Sophyane Learning" in output

    assert (
        "unavailable; no cloud API configured"
        in output
    )

    assert "Mode: local only" not in output


def test_cloud_only_shows_all_five_modes(
    monkeypatch,
):
    _common(monkeypatch)

    monkeypatch.setattr(
        policy,
        "_local_candidate",
        lambda config, llm: None,
    )

    monkeypatch.setattr(
        policy,
        "_configured_clouds",
        lambda: [
            (
                "gemini",
                "Gemini",
            )
        ],
    )

    monkeypatch.setattr(
        "builtins.input",
        lambda prompt="": "",
    )

    stderr = io.StringIO()

    with redirect_stderr(stderr):
        result = policy.choose_startup_provider()

    output = stderr.getvalue()

    assert result == {}

    assert "1. Sophyane" in output
    assert "2. SLI Graph" in output
    assert "3. Local LLM" in output
    assert "4. Cloud LLM" in output
    assert "5. Sophyane Learning" in output

    assert (
        "unavailable; no local model configured"
        in output
    )

    assert "Gemini" in output


def test_unavailable_cloud_selection_reprompts(
    monkeypatch,
):
    _common(monkeypatch)

    monkeypatch.setattr(
        policy,
        "_local_candidate",
        lambda config, llm: (
            "local_gguf",
            "local",
        ),
    )

    monkeypatch.setattr(
        policy,
        "_configured_clouds",
        lambda: [],
    )

    answers = iter(["4", "1"])

    monkeypatch.setattr(
        "builtins.input",
        lambda prompt="": next(answers),
    )

    stdout = io.StringIO()
    stderr = io.StringIO()

    with (
        redirect_stdout(stdout),
        redirect_stderr(stderr),
    ):
        result = policy.choose_startup_provider()

    assert result == {}

    assert (
        "Cloud LLM unavailable"
        in stdout.getvalue()
    )


def test_unavailable_local_selection_reprompts(
    monkeypatch,
):
    _common(monkeypatch)

    monkeypatch.setattr(
        policy,
        "_local_candidate",
        lambda config, llm: None,
    )

    monkeypatch.setattr(
        policy,
        "_configured_clouds",
        lambda: [
            (
                "gemini",
                "Gemini",
            )
        ],
    )

    answers = iter(["3", "1"])

    monkeypatch.setattr(
        "builtins.input",
        lambda prompt="": next(answers),
    )

    stdout = io.StringIO()
    stderr = io.StringIO()

    with (
        redirect_stdout(stdout),
        redirect_stderr(stderr),
    ):
        result = policy.choose_startup_provider()

    assert result == {}

    assert (
        "Local LLM unavailable"
        in stdout.getvalue()
    )


def test_local_llm_selection_remains_strict_local(
    monkeypatch,
):
    _common(monkeypatch)

    monkeypatch.setattr(
        policy,
        "_local_candidate",
        lambda config, llm: (
            "local_gguf",
            "strict-local-model",
        ),
    )

    monkeypatch.setattr(
        policy,
        "_configured_clouds",
        lambda: [],
    )

    monkeypatch.setattr(
        "builtins.input",
        lambda prompt="": "3",
    )

    monkeypatch.delenv(
        "SOPHYANE_LOCAL_ONLY",
        raising=False,
    )

    monkeypatch.delenv(
        "SOPHYANE_DISABLE_CLOUD_FALLBACK",
        raising=False,
    )

    result = policy.choose_startup_provider()

    assert (
        result["provider"]
        == "local_gguf"
    )

    assert (
        result["model"]
        == "strict-local-model"
    )

    assert (
        policy.os.environ[
            "SOPHYANE_LOCAL_ONLY"
        ]
        == "1"
    )

    assert (
        policy.os.environ[
            "SOPHYANE_DISABLE_CLOUD_FALLBACK"
        ]
        == "1"
    )


def test_noninteractive_local_mode_preserved(
    monkeypatch,
):
    monkeypatch.setattr(
        policy,
        "load_config",
        lambda: {},
    )

    monkeypatch.setattr(
        policy,
        "_load_llm",
        lambda: {},
    )

    monkeypatch.setattr(
        policy,
        "_local_candidate",
        lambda config, llm: (
            "local_gguf",
            "noninteractive-local",
        ),
    )

    monkeypatch.setattr(
        policy,
        "_configured_clouds",
        lambda: [],
    )

    monkeypatch.setattr(
        policy.sys.stdin,
        "isatty",
        lambda: False,
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "local_llm",
    )

    result = policy.choose_startup_provider()

    assert (
        result["provider"]
        == "local_gguf"
    )

    assert (
        result["model"]
        == "noninteractive-local"
    )


def test_no_provider_behavior_preserved(
    monkeypatch,
):
    _common(monkeypatch)

    monkeypatch.setattr(
        policy,
        "_local_candidate",
        lambda config, llm: None,
    )

    monkeypatch.setattr(
        policy,
        "_configured_clouds",
        lambda: [],
    )

    stderr = io.StringIO()

    with redirect_stderr(stderr):
        result = policy.choose_startup_provider()

    assert result == {}

    assert (
        "No usable provider is configured"
        in stderr.getvalue()
    )
