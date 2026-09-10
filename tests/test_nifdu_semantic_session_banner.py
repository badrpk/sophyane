from __future__ import annotations

import sophyane.session_banner as banner


def test_nifdu_reason_labels_are_semantic():
    assert banner._nifdu_reason_label(
        "ready"
    ) == "Ready"

    assert banner._nifdu_reason_label(
        "browser_verification_challenge"
    ) == "Verification required"

    assert banner._nifdu_reason_label(
        "chatgpt_signed_out"
    ) == "Sign-in required"

    assert banner._nifdu_reason_label(
        "prompt_composer_not_detected"
    ) == "ChatGPT not ready"


def test_nifdu_session_does_not_blindly_claim_ready(
    monkeypatch,
):
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "nifdu_llm",
    )
    monkeypatch.setenv(
        "SOPHYANE_SESSION_PROVIDER",
        "nifdu_browser",
    )
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODEL",
        "chatgpt-browser",
    )

    monkeypatch.setattr(
        banner,
        "_nifdu_readiness_state",
        lambda: "Verification required",
    )

    assert (
        banner.session_readiness_state()
        == "Verification required"
    )

    assert (
        banner.model_ready_label()
        == "chatgpt-browser · Verification required"
    )


def test_non_nifdu_session_keeps_ready_status(
    monkeypatch,
):
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
        "local-model",
    )

    assert (
        banner.session_readiness_state()
        == "Ready"
    )

    assert (
        banner.model_ready_label()
        == "local-model · Ready"
    )
