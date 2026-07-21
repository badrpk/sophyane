"""Filesystem and sandbox prerequisites for durable deep-agent execution."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path.home() / ".sophyane"


def _tool(name: str) -> str | None:
    return shutil.which(name)


def capability_report() -> dict[str, Any]:
    return {
        "python": _tool("python3") or _tool("python"),
        "shell": _tool("bash") or _tool("sh"),
        "git": _tool("git"),
        "node": _tool("node"),
        "npm": _tool("npm"),
        "compiler": _tool("clang++") or _tool("g++") or _tool("cc"),
        "curl": _tool("curl"),
        "termux_open_url": _tool("termux-open-url"),
    }


def ensure_runtime_root() -> dict[str, Any]:
    directories = {
        "root": ROOT,
        "workspaces": ROOT / "workspaces",
        "sandboxes": ROOT / "sandboxes",
        "artifacts": ROOT / "artifacts",
        "cache": ROOT / "cache",
        "logs": ROOT / "logs",
        "tmp": ROOT / "tmp",
        "state": ROOT / "state",
    }
    for path in directories.values():
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)

    os.environ.setdefault("SOPHYANE_HOME", str(ROOT))
    os.environ.setdefault("SOPHYANE_WORKSPACES", str(directories["workspaces"]))
    os.environ.setdefault("SOPHYANE_SANDBOX_ROOT", str(directories["sandboxes"]))
    os.environ.setdefault("TMPDIR", str(directories["tmp"]))
    tempfile.tempdir = os.environ["TMPDIR"]

    report = {
        "created_at": time.time(),
        "directories": {key: str(value) for key, value in directories.items()},
        "capabilities": capability_report(),
        "writable": True,
    }
    (directories["state"] / "deep-agent-runtime.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    return report


def prepare_workspace(workspace: Path, *, request: str = "") -> Path:
    ensure_runtime_root()
    root = workspace.resolve()
    root.mkdir(parents=True, exist_ok=True)
    for name in ("input", "output", "tmp", "logs", ".sophyane"):
        (root / name).mkdir(parents=True, exist_ok=True)

    manifest = {
        "workspace": str(root),
        "request": request,
        "created_at": time.time(),
        "isolation": {
            "filesystem_root": str(root),
            "external_writes_forbidden": True,
            "relative_paths_required": True,
        },
        "capabilities": capability_report(),
    }
    (root / ".sophyane" / "sandbox.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return root
