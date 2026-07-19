"""Higher-level routing and execution recovery for Termux agent workflows."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def install_orchestration_patch() -> None:
    from sophyane import execution_runtime as runtime
    from sophyane import tui_v2

    if getattr(runtime, "_orchestration_installed", False):
        return

    original_execution_requested = tui_v2._execution_requested
    original_references_previous = tui_v2._references_previous_project

    def execution_requested(message: str) -> bool:
        text = " ".join(message.lower().split())
        extra = (
            "diagnose", "debug", "giving error", "has error", "error in", "repair",
            "optimize", "profile", "audit", "integrate", "simulate", "benchmark",
            "self-improvement", "self improvement", "start a persistent", "monitor",
            "implement", "demonstrate", "apply reductions", "re-test", "retest",
        )
        return original_execution_requested(message) or any(marker in text for marker in extra)

    def references_previous(message: str) -> bool:
        text = " ".join(message.lower().split())
        extra = (
            "giving error", "has error", "error in it", "fix the error", "diagnose it",
            "last task", "last execution", "last 3", "previous task", "generated game",
        )
        return original_references_previous(message) or any(marker in text for marker in extra)

    tui_v2._execution_requested = execution_requested
    tui_v2._references_previous_project = references_previous

    original_execute = runtime.execute_action

    def execute_action(action: dict[str, Any], workspace: Path, progress: Any) -> tuple[bool, str]:
        normalized = runtime._normalize_action(action) or action
        kind = str(normalized.get("type") or "").strip().lower()

        if kind in {"write_file", "append_file"}:
            path = str(normalized.get("path") or normalized.get("file") or "").strip()
            if not path:
                return False, "File action rejected: missing path. Return a concrete relative filename inside the workspace."
            target = (workspace / path).resolve()
            root = workspace.resolve()
            if target != root and root not in target.parents:
                return False, f"File action rejected: {path} is outside the active workspace. Use a relative path in {workspace}."

            content = str(normalized.get("content") or normalized.get("text") or "")
            if kind == "write_file" and target.exists():
                existing = target.read_text(encoding="utf-8", errors="replace")
                new_starts_document = content.lstrip().lower().startswith(("<!doctype", "<html", "#include", "import ", "from "))
                same_prefix = bool(existing and content and existing[:80] == content[:80])
                if (new_starts_document or same_prefix) and len(content) > len(existing):
                    target.write_text(content, encoding="utf-8")
                    progress(f"Replaced {target} with a larger, more complete version ({len(content)} characters)")
                    return True, f"Replaced {target} with a larger version ({target.stat().st_size} total bytes)."
                if not new_starts_document and not same_prefix:
                    with target.open("a", encoding="utf-8") as handle:
                        handle.write(content)
                    progress(f"Converted repeated write_file to append_file for {target}")
                    return True, f"Appended continuation to {target} ({target.stat().st_size} total bytes)."
                return True, (
                    f"Ignored a shorter or duplicate replacement for {path}. Existing file is {len(existing)} bytes; "
                    "continue with append_file, verification, or a complete larger replacement."
                )

        if kind in {"run", "shell", "run_command", "bash", "run_interactive", "interactive", "play_demo"}:
            command = str(normalized.get("command") or normalized.get("cmd") or normalized.get("content") or "").strip()
            if not command:
                return False, "Command action rejected: missing command. Return a concrete command or respond with completion."

        try:
            ok, result = original_execute(normalized, workspace, progress)
        except (ValueError, OSError) as error:
            return False, f"Action rejected safely: {error}"

        if not ok and result.startswith("Repeated command blocked:"):
            return True, result + ". This inspection already succeeded; choose a different verification or finish with respond."
        if not ok and result.startswith("Repeated write_file blocked"):
            return True, result + " Continue with append_file or verify the existing file."
        return ok, result

    runtime.execute_action = execute_action
    runtime._orchestration_installed = True
