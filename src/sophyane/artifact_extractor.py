"""Provider-neutral artifact extraction and truncation recovery helpers."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

_HTML_START = re.compile(r"(?is)<!doctype\s+html|<html\b")
_FENCE = re.compile(r"(?is)```(?:html)?\s*(<!doctype\s+html.*?</html>|<html\b.*?</html>)\s*```")
_ACTION_TYPES = {
    "update_html", "replace_html", "write_html", "create_html", "artifact",
}


@dataclass(frozen=True)
class Artifact:
    content: str
    source: str
    complete: bool
    path: str = "index.html"


def _complete_html(value: str) -> bool:
    text = value.strip().lower()
    return bool(_HTML_START.search(text)) and text.endswith("</html>")


def _walk(value: Any, trail: str = "json") -> Artifact | None:
    if isinstance(value, str):
        text = value.strip()
        if _HTML_START.search(text):
            return Artifact(text, trail, _complete_html(text))
        return None
    if isinstance(value, list):
        for index, item in enumerate(value):
            found = _walk(item, f"{trail}[{index}]")
            if found:
                return found
        return None
    if not isinstance(value, dict):
        return None

    kind = str(value.get("type") or value.get("kind") or value.get("name") or "").lower()
    path = str(value.get("path") or value.get("file") or "index.html")
    if kind in _ACTION_TYPES or (kind == "write_file" and path.lower().endswith((".html", ".htm"))):
        for key in ("content", "html_content", "html", "artifact", "text"):
            candidate = value.get(key)
            if isinstance(candidate, str) and _HTML_START.search(candidate):
                return Artifact(candidate.strip(), f"{trail}.{key}", _complete_html(candidate), path or "index.html")

    preferred = (
        "action", "html_content", "content", "html", "artifact", "result",
        "output", "candidate", "candidates", "selected_action", "tool_call",
    )
    for key in preferred:
        if key in value:
            found = _walk(value[key], f"{trail}.{key}")
            if found:
                return found
    for key, item in value.items():
        if key not in preferred:
            found = _walk(item, f"{trail}.{key}")
            if found:
                return found
    return None


def _decode_partial_json_string(raw: str) -> str:
    """Decode a possibly truncated JSON string without inventing missing bytes."""
    output: list[str] = []
    escaped = False
    index = 0
    while index < len(raw):
        char = raw[index]
        if escaped:
            mapping = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\", "/": "/"}
            if char == "u" and index + 4 < len(raw):
                token = raw[index + 1:index + 5]
                try:
                    output.append(chr(int(token, 16)))
                    index += 5
                    escaped = False
                    continue
                except ValueError:
                    pass
            output.append(mapping.get(char, char))
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            break
        else:
            output.append(char)
        index += 1
    return "".join(output)


def extract_artifact(text: str) -> Artifact | None:
    raw = str(text or "").strip()
    if not raw:
        return None

    fenced = _FENCE.search(raw)
    if fenced:
        html = fenced.group(1).strip()
        return Artifact(html, "markdown.html", _complete_html(html))

    start = _HTML_START.search(raw)
    if start:
        html = raw[start.start():].strip()
        end = html.lower().rfind("</html>")
        if end >= 0:
            html = html[:end + len("</html>")]
        return Artifact(html, "raw.html", _complete_html(html))

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if parsed is not None:
        found = _walk(parsed)
        if found:
            return found

    # Recover HTML embedded in a truncated JSON action.content string.
    for key in ("content", "html_content", "html", "artifact"):
        match = re.search(rf'(?is)"{key}"\s*:\s*"', raw)
        if not match:
            continue
        decoded = _decode_partial_json_string(raw[match.end():])
        html_start = _HTML_START.search(decoded)
        if html_start:
            html = decoded[html_start.start():].strip()
            return Artifact(html, f"partial-json.{key}", _complete_html(html))
    return None


def continuation_prompt(artifact: Artifact, original_request: str) -> str:
    tail = artifact.content[-500:]
    return (
        "The previous HTML artifact was truncated. Continue the SAME artifact from the exact cutoff below. "
        "Return ONLY the remaining HTML characters; do not restart, do not use JSON, markdown, planning, or commentary. "
        "The final combined document must close script/body/html tags and preserve all requested behavior.\n\n"
        f"Original request: {original_request}\nExact current tail:\n{tail}"
    )


def merge_continuation(existing: str, continuation: str) -> str:
    extra = str(continuation or "").strip()
    fenced = _FENCE.search(extra)
    if fenced:
        extra = fenced.group(1).strip()
    start = _HTML_START.search(extra)
    if start:
        # A provider ignored continuation instructions and returned a replacement.
        replacement = extra[start.start():].strip()
        return replacement if len(replacement) >= len(existing) else existing
    overlap = min(500, len(existing), len(extra))
    for size in range(overlap, 15, -1):
        if existing[-size:] == extra[:size]:
            extra = extra[size:]
            break
    return existing + extra
