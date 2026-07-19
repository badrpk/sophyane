"""Runtime compatibility patch for observable terminal execution.

Keeps compile/test commands captured, but attaches playable terminal programs to
stdin/stdout/stderr so users can actually interact with demos.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any


def _looks_interactive(command: str) -> bool:
    text = " ".join(command.lower().split())
    if any(token in text for token in ("pytest", "py_compile", "compile", "cmake", "make ", "g++", "clang++")):
        return False
    patterns = (
        r"(^|[;&|]\s*)python(?:3)?\s+[^;&|]*(snake|game|demo)",
        r"(^|[;&|]\s*)node\s+[^;&|]*(snake|game|demo)",
        r"(^|[;&|]\s*)\./[^;&|]*(snake|game|demo)",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def install_runtime_patch() -> None:
    from sophyane import execution_runtime as runtime

    if getattr(runtime, "_interactive_patch_installed", False):
        return

    original_execute = runtime.execute_action

    def execute_action(action: dict[str, Any], workspace: Path, progress: Any) -> tuple[bool, str]:
        kind = str(action.get("type") or action.get("action") or "").strip().lower()

        if kind in {"analyze_log", "analyse_log", "analyze", "verify_result", "check_result"}:
            note = str(
                action.get("message")
                or action.get("content")
                or action.get("analysis")
                or "Execution result reviewed; continue to the next concrete action or respond."
            ).strip()
            progress("Analysis checkpoint completed")
            return True, note

        if kind in {"run_interactive", "interactive", "play_demo"}:
            command = str(action.get("command") or action.get("content") or "").strip()
            if not command:
                return False, "Interactive command action did not contain a command."
            progress(f"Launching interactive terminal program: {command}")
            print("\n--- Interactive demo started; use its controls and quit key to return to Sophyane ---\n", flush=True)
            completed = subprocess.run(command, shell=True, cwd=workspace, check=False)
            print("\n--- Interactive demo ended; returning to Sophyane ---\n", flush=True)
            return True, f"Interactive command: {command}\nExit code: {completed.returncode}"

        if kind in {"run", "shell", "run_command", "bash"}:
            command = str(action.get("command") or action.get("content") or "").strip()
            if action.get("interactive") is True or _looks_interactive(command):
                progress(f"Detected playable terminal command: {command}")
                print("\n--- Interactive demo started; use its controls and quit key to return to Sophyane ---\n", flush=True)
                completed = subprocess.run(command, shell=True, cwd=workspace, check=False)
                print("\n--- Interactive demo ended; returning to Sophyane ---\n", flush=True)
                return True, f"Interactive command: {command}\nExit code: {completed.returncode}"

        return original_execute(action, workspace, progress)

    runtime.execute_action = execute_action
    runtime._interactive_patch_installed = True
