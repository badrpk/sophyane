"""Bridge to the optional native Sophyane C++ fast-path kernel."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


def kernel_path() -> Path:
    override = os.environ.get("SOPHYANE_KERNEL", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "share" / "sophyane" / "native" / "sophyane-kernel"


def available() -> bool:
    path = kernel_path()
    return path.is_file() and os.access(path, os.X_OK)


def _call(*args: str, timeout: int = 3) -> dict[str, Any] | None:
    if not available():
        return None
    try:
        completed = subprocess.run(
            [str(kernel_path()), *args],
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    try:
        value = json.loads((completed.stdout or "").strip())
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def classify(message: str) -> str | None:
    result = _call("--classify", message)
    mode = str((result or {}).get("mode") or "")
    return mode if mode in {"chat", "execution"} else None


def workspace_status(workspace: Path) -> dict[str, Any] | None:
    return _call("--workspace-status", str(workspace.resolve()), timeout=5)
