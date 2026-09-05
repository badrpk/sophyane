
"""Compatibility entry point for the observable Sophyane terminal UI."""
from __future__ import annotations

# ---- Compatibility exports for legacy tests ----

SLASH_COMMANDS = {
    "/help",
    "/new",
    "/quit",
    "/model",
    "/status",
    "/doctor",
    "/local",
}

class Style:
    """Compatibility shim for legacy tests."""

    def __init__(self, color: bool = True):
        self.color = color

    def bold(self, text: str) -> str:
        return text

    def cyan(self, text: str) -> str:
        return text

# ---- End compatibility exports ----



import json
import re
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


def _effective_workspace(kwargs: dict[str, Any]) -> Path:
    """Resolve the workspace before snapshots and adaptive wrappers run."""
    original_request = str(kwargs.get("original_request") or "")
    match = re.search(
        r"(?:work exclusively inside|work inside|workspace(?: is|:)?|"
        r"current working directory(?: is|:)?)\s*[`\"']?"
        r"(/[A-Za-z0-9_./~+@%=-]+)",
        original_request,
        flags=re.IGNORECASE,
    )
    if match:
        return Path(match.group(1).rstrip("`\"'.,;:")).expanduser().resolve()

    normalized = " ".join(original_request.lower().split())
    caller_directory_markers = (
        "current working directory",
        "in the current directory",
        "work exclusively inside",
        "work inside",
        "inside the workspace",
    )
    if any(marker in normalized for marker in caller_directory_markers):
        return Path.cwd().resolve()

    supplied = kwargs.get("workspace")
    return Path(supplied or Path.cwd()).expanduser().resolve()


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
    from sophyane.mobile_sensor_routing import install_mobile_sensor_routing
    from sophyane.mobile_permission_center import install_mobile_permission_center
    from sophyane.mobile_capability_prompt import install_mobile_capability_prompt
    from sophyane.runtime_self_contained_html_patch import install_self_contained_html_patch
    from sophyane.runtime_snake_semantic_repair import install_snake_semantic_repair
    from sophyane.runtime_cloud_timeout_patch import install_cloud_timeout_patch
    from sophyane.workspace_attachment import install_workspace_attachment
    from sophyane import execution_runtime
    from sophyane.browser_runtime_v2 import open_verified_browser
    from sophyane.execution_kernel import ExecutionKernel
    from sophyane.post_build_menu import PostBuildMenu

    install()
    install_self_contained_html_patch()
    install_incremental_browser_edit()
    install_game_validation()
    install_html_repair_policy()
    install_browser_partial_recovery()
    install_browser_failure_gate()
    install_mobile_sensor_routing()
    install_mobile_permission_center()
    install_mobile_capability_prompt()
    install_workspace_attachment()
    # TUI installation happens after cli_entry and replaces the continuation
    # prompt. Re-apply semantic repair here so it remains the final authority.
    install_snake_semantic_repair()

    original_execute_action = execution_runtime.execute_action

    def execute_action_with_verified_browser(action: dict[str, Any], workspace: Any, progress: Any):
        kind = str(action.get("type") or action.get("action") or "").strip().lower()
        if kind in {"open_browser", "browser"}:
            return open_verified_browser(workspace, progress)
        return original_execute_action(action, workspace, progress)

    execution_runtime.execute_action = execute_action_with_verified_browser

    from sophyane import tui_v2

    # Cloud planning and complete browser artifacts can exceed one minute.
    # Keep local providers bounded while giving cloud providers 120 seconds.
    install_cloud_timeout_patch(tui_v2)

    # SOPHYANE_POST_BUILD_GATE_V19
    from sophyane.request_classification import (
        requires_post_build_menu as _requires_post_build_menu,
    )


    def run_with_post_build_menu(**kwargs: Any) -> str:
        effective_kwargs = dict(kwargs)
        workspace = _effective_workspace(effective_kwargs)
        workspace.mkdir(parents=True, exist_ok=True)
        effective_kwargs["workspace"] = workspace

        before = _artifact_snapshot(workspace)
        result = run_adaptive_loop(**effective_kwargs)

        # SOPHYANE_POST_BUILD_GATE_V17
        original_request = str(
            effective_kwargs.get("original_request")
            or ""
        )

        show_project_menu = (
            _requires_post_build_menu(original_request)
        )

        if (
            show_project_menu
            and _execution_succeeded(
                result,
                before,
                workspace,
            )
        ):
            # Keep the execution/RSI pipeline non-blocking. HITL actions are
            # opt-in: only requests that explicitly ask to publish/package
            # open the interactive action menu. Normal builds return to the
            # Sophyane prompt so the user can inject follow-ups at any time.
            request_text = original_request.casefold()
            explicit_handoff = any(
                marker in request_text
                for marker in ("publish", "deploy", "package", "export", "app icon")
            )
            if explicit_handoff or os.environ.get("SOPHYANE_AUTO_POST_BUILD_MENU") == "1":
                PostBuildMenu(workspace).run()
            else:
                print(
                    "\nProject verified. Continue with another instruction, or ask \"publish website\", \"open the website\", or \"show project files\".",
                    flush=True,
                )
        elif (
            show_project_menu
            and workspace.is_dir()
        ):
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

    def call_provider_with_execution_recovery(
        self: Any,
        message: str,
        *,
        timeout: int | None = None,
    ) -> Any:
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
