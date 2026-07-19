"""Bridge to the optional native Sophyane C++ fast-path kernel."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

_BUILD_ATTEMPTED = False


def kernel_path() -> Path:
    override = os.environ.get("SOPHYANE_KERNEL", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "share" / "sophyane" / "native" / "sophyane-kernel"


def source_path() -> Path:
    override = os.environ.get("SOPHYANE_KERNEL_SOURCE", "").strip()
    if override:
        return Path(override).expanduser()
    base = Path(os.environ.get("SOPHYANE_HOME", Path.home() / ".local" / "share" / "sophyane"))
    return base / "system" / "native" / "sophyane_kernel.cpp"


def ensure_built() -> bool:
    global _BUILD_ATTEMPTED
    target = kernel_path()
    if target.is_file() and os.access(target, os.X_OK):
        return True
    if _BUILD_ATTEMPTED or os.environ.get("SOPHYANE_DISABLE_NATIVE", "0") == "1":
        return False
    _BUILD_ATTEMPTED = True
    source = source_path()
    compiler = next((shutil.which(name) for name in ("clang++", "g++", "c++") if shutil.which(name)), None)
    if not source.is_file() or not compiler:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".new")
    try:
        completed = subprocess.run(
            [compiler, "-std=c++17", "-O3", "-DNDEBUG", str(source), "-o", str(temporary)],
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
        if completed.returncode != 0:
            temporary.unlink(missing_ok=True)
            return False
        temporary.chmod(0o755)
        check = subprocess.run([str(temporary), "--version"], capture_output=True, timeout=5, check=False)
        if check.returncode != 0:
            temporary.unlink(missing_ok=True)
            return False
        temporary.replace(target)
        return True
    except (OSError, subprocess.TimeoutExpired):
        temporary.unlink(missing_ok=True)
        return False


def available() -> bool:
    return ensure_built()


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
