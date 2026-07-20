"""Compatibility entry point for the observable Sophyane terminal UI."""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any


def run_grok_style_tui(*, config: dict[str, Any], verbose: bool) -> int:
    """Launch the observable TUI through the canonical execution kernel."""
    from sophyane.adaptive_execution import install, run_adaptive_loop
    from sophyane.incremental_browser_edit import install_incremental_browser_edit
    from sophyane.game_validation import install_game_validation
    from sophyane.html_repair_policy import install_html_repair_policy
    from sophyane.browser_partial_recovery import install_browser_partial_recovery
    from sophyane.workspace_attachment import install_workspace_attachment
    from sophyane import execution_runtime
    from sophyane.browser_runtime_v2 import open_verified_browser
    from sophyane.execution_kernel import ExecutionKernel
    from sophyane.post_build_menu import PostBuildMenu

    install()
    install_incremental_browser_edit()
    install_game_validation()
    install_html_repair_policy()
    install_browser_partial_recovery()
    install_workspace_attachment()

    original_execute_action = execution_runtime.execute_action

    def execute_action_with_verified_browser(action: dict[str, Any], workspace: Any, progress: Any):
        kind = str(action.get("type") or action.get("action") or "").strip().lower()
        if kind in {"open_browser", "browser"}:
            return open_verified_browser(workspace, progress)
        return original_execute_action(action, workspace, progress)

    execution_runtime.execute_action = execute_action_with_verified_browser

    from sophyane import tui_v2

    def run_with_post_build_menu(**kwargs: Any) -> str:
        result = run_adaptive_loop(**kwargs)
        workspace = kwargs.get("workspace")
        if workspace is not None and any(workspace.iterdir()):
            PostBuildMenu(workspace).run()
        return result

    kernel = ExecutionKernel(run_with_post_build_menu)
    tui_v2.run_structured_loop = kernel.run_structured_loop

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
    runner = getattr(tui_v2, "run_tui", None) or getattr(tui_v2, "run_observable_tui", None)
    if runner is None:
        raise RuntimeError("No compatible TUI entry point found in sophyane.tui_v2")
    return runner(config=config, verbose=verbose)
