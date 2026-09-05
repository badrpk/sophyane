"""Small, deterministic task chunking primitives for constrained local models.

The coordinator deliberately owns structure and merging; a GGUF worker only
handles one bounded chunk at a time.  This module is provider-independent so
it can be tested without starting llama-server.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


@dataclass(frozen=True)
class LocalChunk:
    id: str
    title: str
    instruction: str
    depends_on: tuple[str, ...] = ()


def decompose_request(request: str) -> tuple[LocalChunk, ...]:
    """Turn a request into bounded chunks using explicit bullet requirements."""
    text = " ".join(str(request or "").split())
    if not text:
        return ()
    # Wrapped prose is one requirement; only explicit bullets or completed
    # sentences become independent work units.
    raw_lines = [p for p in str(request).splitlines() if p.strip(" -\t")]
    lines = [p.strip(" -\t") for p in raw_lines]
    parts: list[str] = []
    current = ""
    for raw_line, line in zip(raw_lines, lines):
        if raw_line.lstrip().startswith(("-", "*")) and current:
            parts.append(current)
            current = ""
        current = f"{current} {line}".strip()
        if line.endswith((".", "?", "!")):
            parts.append(current)
            current = ""
    if current:
        parts.append(current)
    if len(parts) <= 1:
        return (LocalChunk("task-1", "Implementation", text),)
    chunks = []
    previous = ""
    for index, part in enumerate(parts, 1):
        chunk_id = f"task-{index}"
        chunks.append(LocalChunk(chunk_id, part[:80], part, (previous,) if previous else ()))
        previous = chunk_id
    return tuple(chunks)


def parse_chunk_artifact(raw: str) -> dict[str, Any]:
    """Validate one worker response without accepting prose as an artifact."""
    value = json.loads(str(raw or ""))
    if not isinstance(value, dict):
        raise ValueError("chunk artifact must be an object")
    files = value.get("files", [])
    if not isinstance(files, list):
        raise ValueError("chunk files must be a list")
    for item in files:
        if not isinstance(item, dict) or not item.get("path"):
            raise ValueError("each chunk file needs a path")
        path = str(item["path"])
        if path.startswith("/") or ".." in path.split("/"):
            raise ValueError("chunk file path escapes workspace")
        if item.get("operation", "write") not in {"write", "append"}:
            raise ValueError("unsupported chunk file operation")
        if not isinstance(item.get("content", ""), str):
            raise ValueError("chunk file content must be text")
    return value


def merge_chunk_artifacts(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge validated artifacts, rejecting conflicting writes."""
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for artifact in artifacts:
        for item in artifact.get("files", []):
            path = str(item["path"])
            operation = item.get("operation", "write")
            if operation == "write" and path in merged:
                raise ValueError(f"conflicting chunk write: {path}")
            if path not in merged:
                merged[path] = {"path": path, "operation": operation, "content": item.get("content", "")}
                order.append(path)
            elif operation == "append":
                merged[path]["content"] += item.get("content", "")
    return {"files": [merged[path] for path in order]}
