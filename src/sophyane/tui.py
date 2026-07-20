"""Compatibility entry point for the observable Sophyane terminal UI."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def _artifact_snapshot(workspace: Path) -> dict[str, tuple[int, int]]:
    """Capture user-facing artifacts while ignoring recovery and server metadata."""
    ignored = {".sophyane-partial-index.html"}
    snapshot: dict[str, tuple[int, int]] = {}
    if not workspace.is_dir():
        return snapshot
    for path in workspace.rglob("*"):
        if not path.is_file() or path.name in ignored or path.name.startswith("server-"):
            continue
        try:
            stat = path.stat()
            snapshot[str(path.relative_to(workspace))] = (stat.st_size, stat.st_mtime_ns)
        except OSError:
            continue
    return snapshot


def _execution_succeeded(result: str, before: dict[str, tuple[int, int]], workspace: Path) -> bool:
    """Require a positive runtime result and a real new or changed artifact."""
    text = (result or "").lower()
    failure_markers = (
        "execution stopped safely",
        "execution loop failed",
        "stopped after bounded",
        "could not produce a usable artifact",
        "provider html rejected",
        "failed safely",
    )
    if any(marker in text for marker in failure_markers):
        return False
    after = _artifact_snapshot(workspace)
    if not after:
        return False
    return after != before


def run_grok_style_tui(*, config: dict[str, Any], verbose: bool) -> int:
    """Launch the observable TUI through the canonical execution kernel."""
    from sophyane.adaptive_execution import install, run_adaptive_loop
    from sophyane.incremental_browser_edit import install_incremental_browser_edit
    from sophyane.game_validation import install_game_validation
    from sophyane.html_repair_policy import install_html_repair_policy
    from sophyane.browser_partial_recovery import install_browser_partial_recovery
    from sophyane.browser_failure_gate import install_browser_failure_gate
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
    install_browser_failure_gate()
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
        workspace = Path(kwargs.get("workspace")).resolve()
        before = _artifact_snapshot(workspace)
        result = run_adaptive_loop(**kwargs)
        if _execution_succeeded(result, before, workspace):
            PostBuildMenu(workspace).run()
        elif workspace.is_dir():
            print(
                "\n❌ Project build/update did not complete. "
                "The previous working files were preserved; the success menu was not opened.",
                flush=True,
            )
            partial = workspace / ".sophyane-partial-index.html"
            if partial.is_file():
                print(f"Rejected partial preserved at: {partial}", flush=True)
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
