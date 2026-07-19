"""Compatibility entry point for the observable Sophyane terminal UI."""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any


def run_grok_style_tui(*, config: dict[str, Any], verbose: bool) -> int:
    """Launch the observable TUI with provider-driven adaptive execution."""
    from sophyane.adaptive_execution import install, run_adaptive_loop
    from sophyane import execution_runtime
    from sophyane.browser_runtime_v2 import open_verified_browser

    install()

    # Force every browser action through the new uniquely named verified launcher.
    # This bypasses any stale bytecode from earlier port-8000 implementations.
    original_execute_action = execution_runtime.execute_action

    def execute_action_with_verified_browser(action: dict[str, Any], workspace: Any, progress: Any):
        kind = str(action.get("type") or action.get("action") or "").strip().lower()
        if kind in {"open_browser", "browser"}:
            return open_verified_browser(workspace, progress)
        return original_execute_action(action, workspace, progress)

    execution_runtime.execute_action = execute_action_with_verified_browser

    from sophyane import tui_v2

    # Bind explicitly because tui_v2 imports this function by value.
    tui_v2.run_structured_loop = run_adaptive_loop

    # Tiny local models sometimes answer the first execution prompt with prose rather
    # than JSON. Preserve that reply as recovery context, but make it structurally
    # visible so tui_v2 enters the adaptive loop instead of stopping before recovery.
    original_call_provider = tui_v2.ObservableTUI.call_provider

    def call_provider_with_execution_recovery(self: Any, message: str, *, timeout: int = 60) -> Any:
        response = original_call_provider(self, message, timeout=timeout)
        execution_prompt = message.startswith("Execute this new project request:") or message.startswith(
            "Continue the SAME existing project"
        )
        if not execution_prompt:
            return response
        text = getattr(response, "text", str(response))
        stripped = text.lstrip()
        try:
            parsed = json.loads(stripped)
        except (json.JSONDecodeError, TypeError):
            parsed = None
        if isinstance(parsed, dict) or stripped.startswith("{"):
            return response
        return SimpleNamespace(text=json.dumps({"recovery_text": text}, ensure_ascii=False))

    tui_v2.ObservableTUI.call_provider = call_provider_with_execution_recovery
    return tui_v2.run_observable_tui(config=config, verbose=verbose)
