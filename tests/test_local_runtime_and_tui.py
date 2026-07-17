from __future__ import annotations

from sophyane.local_runtime import (
    HF_GGUF_CATALOG,
    choose_hf_gguf,
    is_credit_or_auth_failure,
    profile_hardware,
    recommend_models,
)
from sophyane.tui import SLASH_COMMANDS, Style, looks_like_coding_task


def test_hardware_profile_has_tier() -> None:
    profile = profile_hardware()
    assert profile.ram_mb > 0
    assert profile.tier in {"nano", "micro", "small", "standard"}
    models = recommend_models(profile)
    assert models
    assert all(isinstance(item[0], str) for item in models)


def test_credit_failure_detection() -> None:
    assert is_credit_or_auth_failure("HTTP 429 insufficient_quota")
    assert is_credit_or_auth_failure("Your prepayment credits are depleted")
    assert is_credit_or_auth_failure("All LLM providers failed")
    assert not is_credit_or_auth_failure("syntax error in user code")


def test_hf_gguf_catalog_covers_all_tiers() -> None:
    for tier in ("nano", "micro", "small", "standard"):
        assert tier in HF_GGUF_CATALOG
        assert HF_GGUF_CATALOG[tier]
        for spec in HF_GGUF_CATALOG[tier]:
            assert spec.repo
            assert spec.filename.endswith(".gguf")
            assert spec.hf_urls()


def test_choose_hf_gguf_returns_spec() -> None:
    spec = choose_hf_gguf()
    assert spec.filename.endswith(".gguf")
    assert spec.size_mb > 0


def test_slash_commands_cover_grok_core() -> None:
    for name in ("/help", "/new", "/quit", "/model", "/status", "/doctor", "/local"):
        assert name in SLASH_COMMANDS


def test_style_noop_without_color() -> None:
    style = Style(False)
    assert style.bold("x") == "x"
    assert style.cyan("y") == "y"


def test_interactive_coding_intent_routes_to_execution_runtime() -> None:
    assert looks_like_coding_task(
        "Create a production-ready C++17 inventory CLI, compile it, "
        "run automated tests, and repair failures."
    )
    assert looks_like_coding_task("Fix the bug and run the tests")
    assert not looks_like_coding_task("What is the relationship between Fatima and Alyan?")
