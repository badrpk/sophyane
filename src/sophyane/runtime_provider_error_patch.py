"""Prevent provider failure messages from being parsed as model plans."""
from __future__ import annotations


def install_provider_error_patch() -> None:
    from sophyane import tui_v2

    if getattr(tui_v2.ObservableTUI, "_provider_error_patch", False):
        return
    original = tui_v2.ObservableTUI.call_provider

    def call_provider(self, message: str, *, timeout: int = 60):
        value = original(self, message, timeout=timeout)
        text = str(getattr(value, "text", value) or "").strip()
        failure_prefixes = (
            "Sophyane could not reach any working LLM provider.",
            "Configured local provider '",
            "All LLM providers failed.",
            "Sophyane encountered an error:",
        )
        if text.startswith(failure_prefixes):
            raise RuntimeError(text)
        return value

    tui_v2.ObservableTUI.call_provider = call_provider
    tui_v2.ObservableTUI._provider_error_patch = True
