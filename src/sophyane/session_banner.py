from __future__ import annotations
import os


# SOPHYANE_NIFDU_SEMANTIC_SESSION_BANNER_V1
def _nifdu_reason_label(reason: str) -> str:
    value = str(reason or "").strip().lower()

    return {
        "ready": "Ready",
        "browser_verification_challenge": "Verification required",
        "chatgpt_signed_out": "Sign-in required",
        "chatgpt_usage_limit": "Usage limit reached",
        "prompt_composer_not_detected": "ChatGPT not ready",
        "chatgpt_not_interactive": "ChatGPT not interactive",
        "invalid_readiness_payload": "ChatGPT not ready",
    }.get(
        value,
        "ChatGPT not ready",
    )


def _nifdu_readiness_state() -> str:
    """Observe NIFDU/ChatGPT readiness without mutating the browser."""

    try:
        from sophyane.providers import nifdu_cdp_bridge as bridge

        page = bridge.chat_page()
        cdp = bridge.CDP(page)

        try:
            cdp.call("Runtime.enable")
            readiness = bridge.chatgpt_readiness(cdp)
        finally:
            cdp.close()

        if not isinstance(readiness, dict):
            return "ChatGPT not ready"

        return _nifdu_reason_label(
            str(readiness.get("reason") or "")
        )

    except Exception:
        # CDP/browser absence is not semantic readiness.
        # Do not claim Ready merely because the provider is configured.
        return "Browser unavailable"


def session_readiness_state() -> str:
    mode = str(
        os.environ.get("SOPHYANE_SESSION_MODE")
        or ""
    ).strip().lower()

    provider = str(
        os.environ.get("SOPHYANE_SESSION_PROVIDER")
        or ""
    ).strip().lower()

    if (
        mode == "nifdu_llm"
        or provider in {
            "nifdu_browser",
            "browser",
            "chatgpt_browser",
        }
    ):
        return _nifdu_readiness_state()

    return "Ready"

def model_ready_label(model: str | None = None) -> str:
    if os.environ.get("SOPHYANE_SLI_ONLY") == "1" or os.environ.get("SOPHYANE_SESSION_MODE") == "sli_chunks":
        return ("SLI Graph · Ready" if os.environ.get("SOPHYANE_SLI_GRAPH") == "1" else "SLI chunks · Ready")
    # Explicit startup provider/model selection is session-scoped
    # authority. Never display a stale persisted model when the current
    # process selected another provider such as NIFDU Browser.
    session_model = str(
        os.environ.get(
            "SOPHYANE_SESSION_MODEL"
        )
        or ""
    ).strip()

    label = (
        session_model
        or (model or "").strip()
        or "model"
    )

    return f"{label} · {session_readiness_state()}"
