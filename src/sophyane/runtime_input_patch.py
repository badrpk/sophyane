"""Local interception for shell-like input typed inside the Sophyane TUI."""
from __future__ import annotations


def install_input_patch() -> None:
    try:
        from sophyane import tui_v2
    except ImportError:
        return
    if getattr(tui_v2, "_input_patch_installed", False):
        return

    original = tui_v2._simple_chat_reply

    def simple_chat_reply(message: str) -> str | None:
        text = " ".join(message.strip().lower().split())
        if text in {"sophyane", "$ sophyane", "~ $ sophyane"}:
            return (
                "Sophyane is already running. Enter a request normally, or use "
                "`/new`, `/setup`, `/status`, `/help`, or `/quit`."
            )
        if text in {"clear", "cls"}:
            return "Use your terminal clear shortcut after leaving Sophyane, or continue with a request here."
        if text in {"help", "/help", "sophyane --help"}:
            return (
                "Commands: `/new` fresh project, `/inspect` current plan/files, "
                "`/trace` raw model output, `/setup` providers, `/status` active chain, `/quit` exit."
            )
        return original(message)

    tui_v2._simple_chat_reply = simple_chat_reply
    tui_v2._input_patch_installed = True
