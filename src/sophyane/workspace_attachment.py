"""Attach existing launch directories and decode provider-wrapped HTML artifacts."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable


HTML_KEYS = ("content", "html", "text", "source", "tool_code", "code")


def _looks_like_project(path: Path) -> bool:
    if not path.is_dir():
        return False
    ignored = {Path.home(), Path.home() / ".sophyane", Path.home() / ".sophyane" / "workspaces"}
    if path.resolve() in {p.resolve() for p in ignored if p.exists()}:
        return False
    markers = ("index.html", "package.json", "pyproject.toml", "Cargo.toml", "Makefile", ".git")
    return any((path / marker).exists() for marker in markers)


def _html_candidates(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        lower = value.lower()
        if ("<!doctype html" in lower or "<html" in lower) and "</html>" in lower:
            found.append(value)
    elif isinstance(value, dict):
        for key in HTML_KEYS:
            if key in value:
                found.extend(_html_candidates(value[key]))
        for key, item in value.items():
            if key not in HTML_KEYS:
                found.extend(_html_candidates(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_html_candidates(item))
    return found


def _named_json_strings(raw: str) -> list[str]:
    """Decode complete JSON string values from common artifact fields."""
    values: list[str] = []
    decoder = json.JSONDecoder()
    names = "|".join(re.escape(name) for name in HTML_KEYS)
    for match in re.finditer(rf'"(?:{names})"\s*:\s*', raw or "", re.I):
        try:
            value, _ = decoder.raw_decode((raw or "")[match.end():])
        except json.JSONDecodeError:
            continue
        if isinstance(value, str):
            values.append(value)
    return values


def _decode_truncated_json_string(fragment: str) -> str | None:
    """Best-effort decode of an unterminated JSON string value."""
    if not fragment.startswith('"'):
        return None
    body = fragment[1:]
    escaped = False
    end = None
    for index, char in enumerate(body):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            end = index
            break
    if end is not None:
        body = body[:end]
    while body.endswith("\\"):
        body = body[:-1]
    try:
        return json.loads('"' + body + '"')
    except json.JSONDecodeError:
        return bytes(body, "utf-8").decode("unicode_escape", errors="replace")


def extract_embedded_html(raw: str) -> str | None:
    """Return the longest complete HTML document embedded in JSON or mixed text."""
    candidates: list[str] = []
    decoder = json.JSONDecoder()
    text = raw or ""

    try:
        candidates.extend(_html_candidates(json.loads(text.strip())))
    except (json.JSONDecodeError, TypeError):
        for match in re.finditer(r"[\[{]", text):
            try:
                value, _ = decoder.raw_decode(text[match.start():])
            except json.JSONDecodeError:
                continue
            candidates.extend(_html_candidates(value))

    candidates.extend(_named_json_strings(text))

    clean: list[str] = []
    for candidate in candidates:
        lower = candidate.lower()
        start = lower.find("<!doctype html")
        if start < 0:
            start = lower.find("<html")
        end = lower.rfind("</html>")
        if start >= 0 and end > start:
            clean.append(candidate[start:end + len("</html>")].strip())
    return max(clean, key=len) if clean else None


def extract_embedded_partial_html(raw: str) -> str | None:
    """Recover HTML from a complete or truncated JSON string artifact field."""
    candidates = _named_json_strings(raw or "")
    names = "|".join(re.escape(name) for name in HTML_KEYS)
    for match in re.finditer(rf'"(?:{names})"\s*:\s*', raw or "", re.I):
        decoded = _decode_truncated_json_string((raw or "")[match.end():])
        if decoded:
            candidates.append(decoded)

    partials: list[str] = []
    for candidate in candidates:
        lower = candidate.lower()
        start = lower.find("<!doctype html")
        if start < 0:
            start = lower.find("<html")
        if start >= 0:
            partial = candidate[start:].strip()
            if len(partial) >= 120:
                partials.append(partial)
    return max(partials, key=len) if partials else None


def install_workspace_attachment() -> None:
    """Patch the TUI and browser extractors once."""
    from sophyane import adaptive_execution as adaptive
    from sophyane import tui_v2

    original_extract: Callable[[str], str | None] = adaptive._extract_html
    if not getattr(original_extract, "_sophyane_embedded_html", False):
        def extract(raw: str) -> str | None:
            embedded = extract_embedded_html(raw)
            if embedded:
                return embedded
            direct = original_extract(raw)
            if direct and direct.lstrip().lower().startswith(("<!doctype html", "<html")):
                return direct
            return direct
        setattr(extract, "_sophyane_embedded_html", True)
        adaptive._extract_html = extract

    original_partial: Callable[[str], str | None] = adaptive._extract_partial_html
    if not getattr(original_partial, "_sophyane_embedded_partial_html", False):
        def extract_partial(raw: str) -> str | None:
            embedded = extract_embedded_partial_html(raw)
            if embedded:
                return embedded
            return original_partial(raw)
        setattr(extract_partial, "_sophyane_embedded_partial_html", True)
        adaptive._extract_partial_html = extract_partial

    original_init = tui_v2.ObservableTUI.__init__
    if not getattr(original_init, "_sophyane_workspace_attachment", False):
        def init(self: Any, *args: Any, **kwargs: Any) -> None:
            original_init(self, *args, **kwargs)
            launch = Path(os.environ.get("SOPHYANE_LAUNCH_DIR") or os.getcwd()).expanduser().resolve()
            if _looks_like_project(launch):
                self.active_workspace = launch
                self.active_request = f"Existing project in {launch}"
                self.project_requirements = [self.active_request]
        setattr(init, "_sophyane_workspace_attachment", True)
        tui_v2.ObservableTUI.__init__ = init

    original_workspace_for = tui_v2.ObservableTUI._workspace_for
    if not getattr(original_workspace_for, "_sophyane_workspace_attachment", False):
        def workspace_for(self: Any, continuing: bool) -> Path:
            if self.active_workspace and self.active_workspace.exists():
                self.progress(f"Reusing workspace: {self.active_workspace}")
                return self.active_workspace
            return original_workspace_for(self, continuing)
        setattr(workspace_for, "_sophyane_workspace_attachment", True)
        tui_v2.ObservableTUI._workspace_for = workspace_for
