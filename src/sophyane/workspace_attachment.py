"""Attach existing launch directories and decode provider-wrapped HTML artifacts."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable


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
        preferred = ("content", "html", "text", "source")
        for key in preferred:
            if key in value:
                found.extend(_html_candidates(value[key]))
        for key, item in value.items():
            if key not in preferred:
                found.extend(_html_candidates(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_html_candidates(item))
    return found


def extract_embedded_html(raw: str) -> str | None:
    """Return the longest complete HTML document embedded in JSON or mixed text."""
    candidates: list[str] = []
    decoder = json.JSONDecoder()
    text = raw or ""

    # Parse a normal JSON response first, then tolerate prose/multiple JSON objects.
    try:
        candidates.extend(_html_candidates(json.loads(text.strip())))
    except (json.JSONDecodeError, TypeError):
        for match in re.finditer(r"[\[{]", text):
            try:
                value, _ = decoder.raw_decode(text[match.start():])
            except json.JSONDecodeError:
                continue
            candidates.extend(_html_candidates(value))

    # Also decode individual JSON string values named content.
    for match in re.finditer(r'"(?:content|html|source)"\s*:\s*', text, re.I):
        try:
            value, _ = decoder.raw_decode(text[match.end():])
        except json.JSONDecodeError:
            continue
        candidates.extend(_html_candidates(value))

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


def install_workspace_attachment() -> None:
    """Patch the TUI and browser extractor once."""
    from sophyane import adaptive_execution as adaptive
    from sophyane import tui_v2

    original_extract: Callable[[str], str | None] = adaptive._extract_html
    if not getattr(original_extract, "_sophyane_embedded_html", False):
        def extract(raw: str) -> str | None:
            direct = original_extract(raw)
            if direct and direct.lstrip().lower().startswith(("<!doctype html", "<html")):
                return direct
            return extract_embedded_html(raw) or direct
        setattr(extract, "_sophyane_embedded_html", True)
        adaptive._extract_html = extract

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
