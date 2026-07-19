"""Runtime safety guard for generated shell actions."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_SEEN: dict[str, dict[str, int]] = {}


def _unsafe_external_write(command: str, workspace: Path) -> str | None:
    text = command.strip()
    root = str(workspace.resolve())
    if ".." in Path(text.split()[0] if text.split() else ".").parts:
        return "parent-directory traversal"
    write_ops = bool(re.search(r"(?:>|>>|\bcp\b|\bmv\b|\brm\b|\bmkdir\b|\bchmod\b|\btouch\b)", text))
    external_markers = ("~/", "$HOME", "${HOME}", "/data/data/com.termux/files/home", "/sdcard", "/storage/")
    if write_ops and any(marker in text for marker in external_markers) and root not in text:
        return "write outside isolated workspace"
    return None


def install_runtime_safety() -> None:
    from sophyane import execution_runtime as runtime

    if getattr(runtime, "_safety_installed", False):
        return
    original = runtime.execute_action

    def guarded(action: dict[str, Any], workspace: Path, progress: Any):
        normalized = runtime._normalize_action(action) or action
        kind = str(normalized.get("type") or "").lower()
        if kind in {"run", "shell", "run_command", "bash", "run_interactive", "interactive", "play_demo"}:
            command = str(normalized.get("command") or normalized.get("cmd") or normalized.get("content") or "").strip()
            reason = _unsafe_external_write(command, workspace)
            if reason:
                return False, f"Command blocked: {reason}. Use only {workspace}."
            key = str(workspace.resolve())
            counts = _SEEN.setdefault(key, {})
            signature = " ".join(command.split())
            counts[signature] = counts.get(signature, 0) + 1
            if counts[signature] > 1:
                return False, f"Repeated command blocked: {command}"
        return original(normalized, workspace, progress)

    runtime.execute_action = guarded
    runtime._safety_installed = True
