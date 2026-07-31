"""Deterministic capability executors.

These executors run before provider planning when Sophyane already has a
grounded local implementation for the request.

Unsupported requests return ``None`` so the existing provider/adaptive
execution pipeline remains the fallback.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CapabilityExecution:
    ok: bool
    capability_id: str
    text: str
    data: dict[str, Any]
    deterministic: bool = True
    provider_bypassed: bool = True


_FOLDER_WORD_RE = re.compile(
    r"\b(folder|folders|directory|directories)\b",
    re.I,
)

_LIST_CUE_RE = re.compile(
    r"\b(list|show|display|name|names|what|which)\b",
    re.I,
)

_COUNT_CUE_RE = re.compile(
    r"\b(count|number|how\s+many)\b",
    re.I,
)

_EXPLANATION_RE = re.compile(
    r"^\s*(what\s+is|what\s+are|explain|define|meaning\s+of|"
    r"how\s+does|why\s+does)\b",
    re.I,
)


def _normalise(message: str) -> str:
    return " ".join(str(message or "").strip().split())


def _looks_like_folder_listing(message: str) -> bool:
    text = _normalise(message)

    if not text or _EXPLANATION_RE.search(text):
        return False

    if not _FOLDER_WORD_RE.search(text):
        return False

    return bool(_LIST_CUE_RE.search(text) or _COUNT_CUE_RE.search(text))


def _requested_root(message: str, workspace: Path) -> tuple[Path, str]:
    text = _normalise(message).lower()

    if any(
        phrase in text
        for phrase in (
            "home directory",
            "home folder",
            "my home",
            "user home",
            "$home",
            "~/",
        )
    ):
        return Path.home(), "user_home"

    if any(
        phrase in text
        for phrase in (
            "workspace",
            "current project",
            "project folder",
            "repository",
            "repo",
            "current directory",
            "working directory",
            "cwd",
        )
    ):
        return workspace, "active_workspace"

    # Conservative default: operate only inside the active workspace.
    return workspace, "active_workspace"


def _list_folders(message: str, workspace: Path) -> CapabilityExecution:
    root, scope = _requested_root(message, workspace)

    try:
        resolved = root.expanduser().resolve()
    except OSError:
        resolved = root.expanduser().absolute()

    if not resolved.exists():
        payload = {
            "ok": False,
            "capability": "filesystem.list_folders",
            "root": str(resolved),
            "scope": scope,
            "error": "path_not_found",
            "runtime_executed_action": True,
            "provider_bypassed": True,
            "deterministic": True,
            "sli_grounded": True,
        }
        return CapabilityExecution(
            ok=False,
            capability_id="filesystem.list_folders",
            text=json.dumps(payload, indent=2, ensure_ascii=False),
            data=payload,
        )

    if not resolved.is_dir():
        payload = {
            "ok": False,
            "capability": "filesystem.list_folders",
            "root": str(resolved),
            "scope": scope,
            "error": "path_is_not_directory",
            "runtime_executed_action": True,
            "provider_bypassed": True,
            "deterministic": True,
            "sli_grounded": True,
        }
        return CapabilityExecution(
            ok=False,
            capability_id="filesystem.list_folders",
            text=json.dumps(payload, indent=2, ensure_ascii=False),
            data=payload,
        )

    try:
        folders = sorted(
            entry.name
            for entry in resolved.iterdir()
            if entry.is_dir() and not entry.name.startswith(".")
        )
    except PermissionError:
        payload = {
            "ok": False,
            "capability": "filesystem.list_folders",
            "root": str(resolved),
            "scope": scope,
            "error": "permission_denied",
            "runtime_executed_action": True,
            "provider_bypassed": True,
            "deterministic": True,
            "sli_grounded": True,
        }
        return CapabilityExecution(
            ok=False,
            capability_id="filesystem.list_folders",
            text=json.dumps(payload, indent=2, ensure_ascii=False),
            data=payload,
        )
    except OSError as error:
        payload = {
            "ok": False,
            "capability": "filesystem.list_folders",
            "root": str(resolved),
            "scope": scope,
            "error": f"{type(error).__name__}: {error}",
            "runtime_executed_action": True,
            "provider_bypassed": True,
            "deterministic": True,
            "sli_grounded": True,
        }
        return CapabilityExecution(
            ok=False,
            capability_id="filesystem.list_folders",
            text=json.dumps(payload, indent=2, ensure_ascii=False),
            data=payload,
        )

    payload = {
        "ok": True,
        "capability": "filesystem.list_folders",
        "root": str(resolved),
        "scope": scope,
        "runtime_executed_action": True,
        "provider_selected_action": False,
        "provider_bypassed": True,
        "deterministic": True,
        "sli_grounded": True,
        "folder_count": len(folders),
        "folders": folders,
        "truncated": False,
    }

    return CapabilityExecution(
        ok=True,
        capability_id="filesystem.list_folders",
        text=json.dumps(payload, indent=2, ensure_ascii=False),
        data=payload,
    )


def execute_deterministic_capability(
    message: str,
    *,
    workspace: str | Path | None = None,
) -> CapabilityExecution | None:
    """Execute a grounded capability or return ``None`` for normal fallback."""

    request = _normalise(message)
    if not request:
        return None

    base = Path(workspace or Path.cwd()).expanduser()

    # Keep the existing V20 classifier as the semantic authority when present.
    try:
        from sophyane.runtime_filesystem_capabilities_v20 import classify_request

        classified = classify_request(request)
    except Exception:
        classified = None

    capability_id = ""
    if isinstance(classified, str):
        capability_id = classified
    elif isinstance(classified, dict):
        capability_id = str(
            classified.get("capability")
            or classified.get("capability_id")
            or classified.get("action")
            or ""
        )
    elif classified:
        capability_id = str(
            getattr(classified, "capability_id", "")
            or getattr(classified, "capability", "")
            or getattr(classified, "action", "")
        )

    if (
        capability_id == "filesystem.list_folders"
        or capability_id.endswith(".list_folders")
        or _looks_like_folder_listing(request)
    ):
        return _list_folders(request, base)

    return None


def execute_deterministic_text(
    message: str,
    *,
    workspace: str | Path | None = None,
) -> str | None:
    result = execute_deterministic_capability(message, workspace=workspace)
    return result.text if result is not None else None


__all__ = [
    "CapabilityExecution",
    "execute_deterministic_capability",
    "execute_deterministic_text",
]


def try_connector_fast_path(message: str) -> str | None:
    """Generic connector dispatch (manifest-driven)."""
    try:
        from sophyane.connectors.runtime import try_connector_reply
        return try_connector_reply(message)
    except Exception:
        return None

