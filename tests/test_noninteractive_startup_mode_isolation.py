from __future__ import annotations

import os

import pytest

import sophyane.startup_policy as policy

STARTUP_KEYS = (
    "SOPHYANE_SESSION_MODE",
    "SOPHYANE_SLI_GRAPH",
    "SOPHYANE_SLI_ONLY",
    "SOPHYANE_LOCAL_ONLY",
    "SOPHYANE_DISABLE_CLOUD_FALLBACK",
)


@pytest.fixture(autouse=True)
def _purge_startup_env_after_each_test():
    """Hard barrier: production writes os.environ directly."""
    yield
    for key in STARTUP_KEYS:
        os.environ.pop(key, None)


def test_startup_selection_mutates_then_fixture_clears(monkeypatch):
    """Document mutation, then rely on autouse fixture to clear."""
    for key in STARTUP_KEYS:
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("SOPHYANE_SESSION_MODE", "sli_graph")
    monkeypatch.setattr(policy.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(
        policy,
        "load_config",
        lambda: {
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "company": "Google",
        },
    )
    monkeypatch.setattr(
        policy,
        "_load_llm",
        lambda: {
            "active_provider": "gemini",
            "fallback_order": ["gemini"],
            "providers": {},
        },
    )
    monkeypatch.setattr(
        policy,
        "_local_candidate",
        lambda config, llm: ("local_gguf", "qwen-test"),
    )
    monkeypatch.setattr(
        policy,
        "_configured_clouds",
        lambda: [("gemini", "Google Gemini")],
    )

    result = policy.choose_startup_provider()
    assert result["company"] == "SLI"
    assert os.environ.get("SOPHYANE_SLI_ONLY") == "1"
    assert os.environ.get("SOPHYANE_SLI_GRAPH") == "1"


@pytest.mark.parametrize("key", STARTUP_KEYS)
def test_process_environment_is_clean_at_test_boundary(key):
    """After previous tests + autouse purge, env must be clean."""
    assert os.environ.get(key) is None, (
        f"{key} leaked from a previous test: {os.environ.get(key)!r}"
    )
