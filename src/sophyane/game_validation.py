"""Mechanical semantic checks for small provider-generated browser games."""
from __future__ import annotations

import re
from typing import Callable


def _scripts(html: str) -> str:
    return "\n".join(re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.I | re.S))


def _snake_advances(source: str) -> bool:
    """Recognize common ways a generated game advances a snake body."""
    patterns = (
        r"\b[A-Za-z_$][\w$]*\s*\.\s*(?:unshift|push)\s*\(",
        r"\b[A-Za-z_$][\w$]*\s*=\s*\[\s*[A-Za-z_$][\w$]*\s*,\s*\.\.\.",
        r"\b[A-Za-z_$][\w$]*\s*\.\s*splice\s*\(\s*0\s*,\s*0\s*,",
        r"\b(?:advance|move|update|step)[A-Za-z_$\w]*\s*\(",
    )
    return any(re.search(pattern, source, re.I) for pattern in patterns)


def _const_is_reassigned(source: str, name: str) -> bool:
    """Detect real writes to a const while ignoring comparisons and ordinary reads."""
    escaped = re.escape(name)
    assignment = rf"(?<![.\w$]){escaped}\s*(?:(?:\+|-|\*|/|%|&|\||\^|<<|>>|>>>)?=(?!=|>)|\+\+|--)"
    prefix_update = rf"(?:\+\+|--)\s*{escaped}\b"
    return bool(re.search(assignment, source) or re.search(prefix_update, source))


def _snake_problem(html: str, request: str) -> str:
    text = request.lower()
    if "snake" not in text or "game" not in text:
        return ""

    source = _scripts(html)
    lower = source.lower()
    if not source.strip():
        return "snake game contains no JavaScript"
    if "canvas" not in html.lower():
        return "snake game contains no canvas"
    if not re.search(r"\b(?:keydown|keyup|touchstart|pointerdown)\b", lower):
        return "snake game has no keyboard or touch controls"
    if not re.search(r"\b(?:setinterval|settimeout|requestanimationframe)\s*\(", lower):
        return "snake game has no update loop"
    if not _snake_advances(source):
        return "snake game does not advance the snake body"

    for declaration in re.finditer(r"\bconst\s+([A-Za-z_$][\w$]*)\s*=", source):
        name = declaration.group(1)
        tail = source[declaration.end():]
        if _const_is_reassigned(tail, name):
            return f"JavaScript reassigns const variable: {name}"

    move = re.search(r"function\s+(?:move|update|tick|step)\s*\([^)]*\)\s*\{(.*?)\n\s*\}", source, re.I | re.S)
    if move and re.search(r"\bsegment\s*\.", move.group(1), re.I):
        params = re.search(r"function\s+(?:move|update|tick|step)\s*\(([^)]*)\)", move.group(0), re.I)
        if not params or "segment" not in params.group(1):
            return "JavaScript uses undefined variable: segment"

    if re.search(r"\b(?:direction|dir)\s*=\s*\{\s*x\s*:\s*0\s*,\s*y\s*:\s*0\s*\}", source, re.I):
        if not re.search(r"(?:direction|dir)\s*\.\s*[xy]\s*=", source, re.I):
            return "snake direction never changes from zero"

    return ""


def install_game_validation() -> None:
    """Wrap adaptive HTML validation once with semantic game checks."""
    from sophyane import adaptive_execution

    current: Callable[[str, str], str] = adaptive_execution._validate_html
    if getattr(current, "_sophyane_game_validation", False):
        return

    def validate(html: str, request: str) -> str:
        structural = current(html, request)
        if structural:
            return structural
        return _snake_problem(html, request)

    setattr(validate, "_sophyane_game_validation", True)
    adaptive_execution._validate_html = validate
