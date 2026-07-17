from __future__ import annotations

from sophyane.config import load_config


def test_gemini_model_environment_override(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test-model")
    monkeypatch.delenv("SOPHYANE_MODEL", raising=False)

    config = load_config()

    assert config["model"] == "gemini-test-model"


def test_generic_model_override_has_priority(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_MODEL", "gemini-provider-model")
    monkeypatch.setenv("SOPHYANE_MODEL", "explicit-sophyane-model")

    config = load_config()

    assert config["model"] == "explicit-sophyane-model"
