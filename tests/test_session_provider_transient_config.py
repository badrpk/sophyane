from __future__ import annotations

import os
from pathlib import Path

import pytest


SESSION_KEYS = (
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
def clean_session_environment():
    for key in SESSION_KEYS:
        os.environ.pop(
            key,
            None,
        )

    yield

    for key in SESSION_KEYS:
        os.environ.pop(
            key,
            None,
        )


def _baseline(
    provider: str,
) -> dict:
    if provider == "gemini":
        return {
            "provider": "gemini",
            "model": "gemini-3.7-flash",
            "company": "Google Gemini",
            "timeout": 180,
            "temperature": 0.3,
            "max_tokens": 4096,
        }

    return {
        "provider": "local_gguf",
        "model": "qwen2.5-1.5b-instruct-q4_k_m",
        "company": "Local",
        "timeout": 300,
        "temperature": 0.3,
        "max_tokens": 4096,
    }


def test_mode3_source_is_transient():
    text = Path(
        "src/sophyane/startup_policy.py"
    ).read_text(
        encoding="utf-8",
    )

    anchor = (
        'os.environ["SOPHYANE_SESSION_PROVIDER"] '
        '= local_id'
    )

    pos = text.index(
        anchor
    )

    window = text[
        max(
            0,
            pos - 1200,
        ):
        pos + 1200
    ]

    assert (
        "save_config(updated)"
        not in window
    )

    assert (
        'os.environ["SOPHYANE_SESSION_MODEL"] = local_model'
        in window
    )

    assert (
        'os.environ["SOPHYANE_SESSION_TIMEOUT"] = "300"'
        in window
    )


def test_mode4_source_is_transient():
    text = Path(
        "src/sophyane/startup_policy.py"
    ).read_text(
        encoding="utf-8",
    )

    anchor = (
        'os.environ["SOPHYANE_SESSION_PROVIDER"] '
        '= cloud_id'
    )

    pos = text.index(
        anchor
    )

    window = text[
        max(
            0,
            pos - 1200,
        ):
        pos + 1200
    ]

    assert (
        "save_config(updated)"
        not in window
    )

    assert (
        'os.environ["SOPHYANE_SESSION_MODEL"] = cloud_model'
        in window
    )

    assert (
        'os.environ["SOPHYANE_SESSION_TIMEOUT"] = "180"'
        in window
    )


def test_local_session_overrides_stale_cloud_model(
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
        "qwen2.5-1.5b-instruct-q4_k_m",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_TIMEOUT",
        "300",
    )

    captured = {}

    def fake_build(
        _loader,
        config,
    ):
        captured.update(
            config
        )

        return object()

    monkeypatch.setattr(
        "sophyane.providers.fallback."
        "build_fallback_provider",
        fake_build,
    )

    main.create_provider(
        _baseline(
            "gemini"
        )
    )

    assert (
        captured["provider"]
        == "local_gguf"
    )

    assert (
        captured["model"]
        == "qwen2.5-1.5b-instruct-q4_k_m"
    )

    assert (
        captured["timeout"]
        == 300
    )


def test_cloud_session_overrides_stale_local_model(
    monkeypatch,
):
    import sophyane.main as main

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "cloud_llm",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_PROVIDER",
        "gemini",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODEL",
        "gemini-3.7-flash",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_TIMEOUT",
        "180",
    )

    captured = {}

    def fake_build(
        _loader,
        config,
    ):
        captured.update(
            config
        )

        return object()

    monkeypatch.setattr(
        "sophyane.providers.fallback."
        "build_fallback_provider",
        fake_build,
    )

    main.create_provider(
        _baseline(
            "local"
        )
    )

    assert (
        captured["provider"]
        == "gemini"
    )

    assert (
        captured["model"]
        == "gemini-3.7-flash"
    )

    assert (
        captured["timeout"]
        == 180
    )
