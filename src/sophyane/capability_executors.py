"""Deterministic capability executors.

These executors run before provider planning when Sophyane already has a
grounded local implementation for the request.

Unsupported requests return ``None`` so the existing provider/adaptive
execution pipeline remains the fallback.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
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


_EXACT_FILE_WRITE_RE = re.compile(
    r"""
    \b(?:create|write|make)\s+
    (?:a\s+|the\s+)?
    (?:file\s+)?
    (?P<filename>[A-Za-z0-9_.-]+\.[A-Za-z0-9_-]+)
    .*?
    \b(?:containing|with)\s+
    (?:exactly\s+)?
    (?P<content>[A-Za-z0-9_.:-]+)
    """,
    re.I | re.S | re.X,
)


def _parse_exact_file_write(
    message: str,
) -> tuple[str, str] | None:
    """Extract a plain workspace filename and exact one-token content."""
    text = _normalise(message)
    match = _EXACT_FILE_WRITE_RE.search(text)

    if not match:
        return None

    filename = match.group("filename").strip()
    content = match.group("content").strip()

    if (
        not filename
        or not content
        or "/" in filename
        or "\\" in filename
        or filename in {".", ".."}
    ):
        return None

    exactness = any(
        phrase in text.casefold()
        for phrase in (
            "exactly",
            "byte-for-byte",
            "byte for byte",
            "with no newline",
            "without a newline",
            "read the file back",
            "read it back",
            "verify it",
        )
    )

    return (filename, content) if exactness else None


def _exact_file_write(
    message: str,
    workspace: Path,
) -> CapabilityExecution | None:
    parsed = _parse_exact_file_write(message)
    if parsed is None:
        return None

    filename, content = parsed

    try:
        root = workspace.expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)

        target = (root / filename).resolve()

        if target.parent != root:
            raise ValueError("Target must remain in the active workspace.")

        # write_text() does not add a newline.
        target.write_text(content, encoding="utf-8")

        actual = target.read_bytes()
        expected = content.encode("utf-8")

        verified = actual == expected

        payload = {
            "ok": verified,
            "capability": "filesystem.write_exact_verified",
            "path": str(target),
            "relative_path": filename,
            "expected_bytes": len(expected),
            "actual_bytes": len(actual),
            "byte_for_byte_verified": verified,
            "newline_added": actual.endswith(b"\n"),
            "runtime_executed_action": True,
            "provider_selected_action": False,
            "provider_bypassed": True,
            "deterministic": True,
            "sli_grounded": True,
        }

        response_only_verified = bool(
            re.search(
                r"\brespond\s+only\s+(?:with\s+)?VERIFIED\b",
                message,
                re.I,
            )
        )

        output = (
            "VERIFIED"
            if verified and response_only_verified
            else json.dumps(payload, indent=2, ensure_ascii=False)
        )

        return CapabilityExecution(
            ok=verified,
            capability_id="filesystem.write_exact_verified",
            text=output,
            data=payload,
        )

    except Exception as error:
        payload = {
            "ok": False,
            "capability": "filesystem.write_exact_verified",
            "error": f"{type(error).__name__}: {error}",
            "runtime_executed_action": True,
            "provider_bypassed": True,
            "deterministic": True,
            "sli_grounded": True,
        }

        return CapabilityExecution(
            ok=False,
            capability_id="filesystem.write_exact_verified",
            text=json.dumps(payload, indent=2, ensure_ascii=False),
            data=payload,
        )


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

    # Exact workspace file writes are stronger than broad filesystem
    # classification. Handle them before classifiers such as list_folders can
    # misinterpret words like "current workspace".
    exact_write = _exact_file_write(request, base)
    if exact_write is not None:
        return exact_write

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

