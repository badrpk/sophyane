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
    """Detect real writes to a const while ignoring declarations and reads."""
    escaped = re.escape(name)

    # Some callers provide text beginning at the declaration rather than just
    # after it. Remove that one declaration so ``const value = ...`` is not
    # mistaken for a later reassignment.
    searchable = re.sub(
        rf"\bconst\s+{escaped}\s*=\s*[^;]*;?",
        "",
        source,
        count=1,
    )

    assignment = (
        rf"(?<![.\w$]){escaped}\s*"
        rf"(?:(?:\+|-|\*|/|%|&|\||\^|<<|>>|>>>)?=(?!=|>)|\+\+|--)"
    )
    prefix_update = rf"(?:\+\+|--)\s*{escaped}\b"
    return bool(
        re.search(assignment, searchable)
        or re.search(prefix_update, searchable)
    )


def _snake_has_reverse_guard(source: str) -> bool:
    """Require direction changes to reject an immediate 180-degree reversal."""
    lower = source.lower()
    named_guard = all(word in lower for word in ("goingleft", "goingright")) or all(
        word in lower for word in ("goingup", "goingdown")
    )
    vector_guard = bool(
        re.search(r"(?:dx|dir(?:ection)?\.x)\s*!==?\s*-?1", source, re.I)
        and re.search(r"(?:dy|dir(?:ection)?\.y)\s*!==?\s*-?1", source, re.I)
    )
    opposite_map = bool(re.search(r"opposite|reverse|cannotreverse|pendingdirection", lower))
    return named_guard or vector_guard or opposite_map


def _snake_has_single_timer_policy(source: str) -> bool:
    """Avoid stacked intervals when Start or Restart is pressed repeatedly."""
    starts = len(re.findall(r"\bsetinterval\s*\(", source, re.I))
    if starts == 0:
        return True
    return bool(re.search(r"\bclearinterval\s*\(", source, re.I))


def _snake_has_mobile_input(html: str, source: str) -> bool:
    """Require usable phone input and suppression of browser scrolling/zoom gestures."""
    lower_html = html.lower()
    lower_source = source.lower()
    has_buttons = all(token in lower_html for token in ("up", "down", "left", "right"))
    has_handlers = bool(re.search(r"\b(?:pointerdown|touchstart|click)\b", lower_source))
    prevents_scroll = "touch-action" in lower_html or "preventdefault" in lower_source
    return has_buttons and has_handlers and prevents_scroll


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
    if not re.search(r"\b(?:keydown|keyup|touchstart|pointerdown|click)\b", lower):
        return "snake game has no keyboard or touch controls"
    if not re.search(r"\b(?:setinterval|settimeout|requestanimationframe)\s*\(", lower):
        return "snake game has no update loop"
    if not _snake_advances(source):
        return "snake game does not advance the snake body"

    # Apply the complete directional-control stability contract when the
    # artifact actually exposes a four-direction interface. Minimal legacy
    # fixtures may exercise keyboard/click wiring without claiming a complete
    # directional controller.
    lower_html = html.lower()
    has_directional_ui = all(
        token in lower_html
        for token in ("up", "down", "left", "right")
    )

    if has_directional_ui:
        if not _snake_has_reverse_guard(source):
            return "snake controls allow unstable 180-degree reversal"
        if not _snake_has_single_timer_policy(source):
            return "snake game can stack multiple update timers"
        if not _snake_has_mobile_input(html, source):
            return (
                "snake game lacks stable mobile touch controls "
                "or touch-action protection"
            )

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
