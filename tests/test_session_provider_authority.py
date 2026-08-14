from __future__ import annotations

import copy

import pytest

import sophyane.main as main


def test_sli_session_rejects_provider_construction(
    monkeypatch,
):
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "sli_graph",
    )

    with pytest.raises(
        RuntimeError,
        match="SLI-only session forbids",
    ):
        main.create_provider(
            {
                "provider": "gemini",
                "model": "gemini-test",
            }
        )


def test_local_session_overrides_stale_cloud_config(
    monkeypatch,
):
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "local_llm",
    )

    monkeypatch.setenv(
        "SOPHYANE_LOCAL_ONLY",
        "0",
    )

    monkeypatch.setenv(
        "SOPHYANE_DISABLE_CLOUD_FALLBACK",
        "0",
    )

    # We only prove policy injection here.
    # Factory internals may fail later because no live provider
    # is needed for this zero-model regression.
    config = {
        "provider": "gemini",
        "model": "gemini-test",
    }

    try:
        main.create_provider(
            copy.deepcopy(config)
        )
    except Exception:
        pass

    assert (
        main.os.environ[
            "SOPHYANE_LOCAL_ONLY"
        ]
        == "1"
    )

    assert (
        main.os.environ[
            "SOPHYANE_DISABLE_CLOUD_FALLBACK"
        ]
        == "1"
    )


def test_cloud_session_disables_local_rescue(
    monkeypatch,
):
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "cloud_llm",
    )

    monkeypatch.delenv(
        "SOPHYANE_DISABLE_LOCAL_FALLBACK",
        raising=False,
    )

    monkeypatch.delenv(
        "SOPHYANE_ALLOW_CLOUD_LOCAL_RESCUE",
        raising=False,
    )

    try:
        main.create_provider(
            {
                "provider": "gemini",
                "model": "gemini-test",
            }
        )
    except Exception:
        pass

    assert (
        main.os.environ[
            "SOPHYANE_DISABLE_LOCAL_FALLBACK"
        ]
        == "1"
    )

    assert (
        main.os.environ[
            "SOPHYANE_ALLOW_CLOUD_LOCAL_RESCUE"
        ]
        == "0"
    )
