
"""Chunk-level semantic roles for SLI retrieval and composition."""
from __future__ import annotations

import re
from typing import Iterable

from sophyane.code_memory.store import CodeChunk

# role -> signal patterns (code meaning, not product hardcoding)
ROLE_PATTERNS: dict[str, tuple[str, ...]] = {
    "test": (r"\bpytest\b", r"\bunittest\b", r"\bdescribe\(", r"\bit\(", r"assert ", r"TestClient"),
    "ui_shell": (r"<html\b", r"<body\b", r"<div\b", r"document\.", r"getElementById"),
    "canvas_render": (r"<canvas\b", r"getContext\s*\(\s*['\"]2d['\"]", r"fillRect\s*\(", r"clearRect\s*\("),
    "input_keyboard": (r"keydown", r"keyup", r"keyCode", r"event\.key"),
    "input_pointer": (r"pointerdown", r"mousedown", r"touchstart", r"click\b", r"addEventListener"),
    "game_loop": (r"requestAnimationFrame", r"setInterval\s*\(", r"setTimeout\s*\("),
    "state_score": (r"\bscore\b", r"game over", r"lives\b", r"level\b"),
    "web_server": (r"\bFlask\b", r"\bFastAPI\b", r"\bExpress\b", r"@app\.(get|post)", r"app\.route"),
    "http_handler": (r"\brequest\b", r"\bresponse\b", r"\bstatus_code\b", r"res\.send", r"JSONResponse"),
    "data_model": (r"\bclass\b.*=.*BaseModel", r"\bdataclass\b", r"\bSchema\b", r"CREATE TABLE"),
    "build_tool": (r"\bsetup\(", r"\bpyproject\b", r"webpack", r"package\.json"),
}

INTENT_TO_ROLES: dict[str, tuple[str, ...]] = {
    "browser_game": ("canvas_render", "game_loop", "input_keyboard", "input_pointer", "ui_shell", "state_score"),
    "web_app": ("ui_shell", "input_pointer", "http_handler", "web_server"),
    "api": ("web_server", "http_handler", "data_model"),
    "general": (),
}


def infer_roles(text: str, path: str = "", tags: Iterable[str] | None = None) -> list[str]:
    blob = f"{path}\n{text}"
    low_path = (path or "").lower()
    roles: list[str] = []
    name = low_path.split("::")[0]
    if (
        "/tests/" in low_path.replace("\\", "/")
        or name.split("/")[-1].startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".test.js")
    ):
        roles.append("test")
    for role, pats in ROLE_PATTERNS.items():
        if role == "test" and "test" in roles:
            continue
        for pat in pats:
            if re.search(pat, blob, flags=re.I):
                roles.append(role)
                break
    for t in tags or []:
        t = str(t).lower()
        if t in ROLE_PATTERNS and t not in roles:
            roles.append(t)
    # unique preserve order
    out: list[str] = []
    for r in roles:
        if r not in out:
            out.append(r)
    # PYTHON_NO_BROWSER_ROLES
    low_path = (path or "").lower().split("::")[0]
    if low_path.endswith(".py") or low_path.endswith(".pyi"):
        browser = {"ui_shell", "canvas_render", "input_keyboard", "input_pointer", "game_loop"}
        out = [r for r in out if r not in browser]
    return out


def classify_intent(message: str) -> str:
    t = message.lower()
    if any(x in t for x in ("game", "playable", "snake", "pong", "tetris", "canvas game")):
        return "browser_game"
    if any(x in t for x in ("website", "webpage", "landing", "dashboard", "html page")):
        return "web_app"
    if any(x in t for x in ("api", "endpoint", "fastapi", "flask", "route")):
        return "api"
    return "general"


def role_bonus(intent: str, roles: list[str]) -> float:
    if "test" in roles and intent != "general":
        return -1.25
    wanted = INTENT_TO_ROLES.get(intent) or ()
    if not wanted:
        return 0.0
    have = set(roles)
    overlap = len(have & set(wanted))
    return 0.35 * overlap


def semantic_score(message: str, chunk: CodeChunk, base_sim: float) -> float:
    meta = chunk.meta or {}
    roles = list(meta.get("roles") or [])
    if not roles:
        roles = infer_roles(chunk.text, chunk.path or "", chunk.tags)
    intent = classify_intent(message)
    score = float(base_sim)
    score += role_bonus(intent, roles)
    # length usefulness
    n = len(chunk.text or "")
    if n < 80:
        score -= 0.35
    elif n > 500:
        score += 0.08
    score *= max(0.05, float(chunk.weight or 1.0))
    return score
