
"""Infer domain + provides contracts for code chunks (no LLM)."""
from __future__ import annotations
import re
from typing import Any

DOMAIN_MARKERS: dict[str, tuple[str, ...]] = {
    "browser_ui": ("document.", "addEventListener", "<canvas", "getElementById", "querySelector"),
    "language_exercise": ("startExerciseApp", "validateAnswer", "SLI_EXERCISE_ITEMS", "normaliseItems"),
    "action_game": ("requestAnimationFrame", "keydown", "snake", "collision", "fillRect"),
    "http_api": ("FastAPI", "Flask", "@app.", "APIRouter", "starlette", "Request", "Response"),
    "python_tooling": ("argparse", "click.", "pytest", "unittest"),
    "data_model": ("dataclass", "BaseModel", "TypedDict", "schema"),
    "vendor_demo": ("webxr", "polyfill", "todomvc", "execCommand"),
}

PROVIDES_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("document_shell", ("<!doctype", "<html", "<body")),
    ("user_input", ("addEventListener", "keydown", "onclick", "input", "onsubmit")),
    ("rendering", ("getContext", "fillRect", "innerHTML", "textContent", "render")),
    ("application_state", ("useState", "createState", "this.state", "let state")),
    ("game_loop", ("requestAnimationFrame", "setInterval")),
    ("http_endpoint", ("@app.get", "@app.post", "app.route", "router.", "APIRouter")),
    ("entry_point", ("if __name__", "def main(", "DOMContentLoaded", "startExerciseApp")),
    ("rules_validation", ("assert ", "validate", "pytest", "isinstance(")),
    ("error_handling", ("try:", "except ", "raise ", "catch (")),
    ("data_model", ("class ", "dataclass", "BaseModel", "interface ")),
]

BAN_SUBSTR = ("webxr", "polyfill", "todomvc", "bower_components", "min.js")

def infer_domain(text: str, path: str = "") -> str:
    blob = f"{path}\n{text}".lower()
    if any(b in blob for b in BAN_SUBSTR):
        return "vendor_demo"
    scores: dict[str, int] = {}
    for domain, marks in DOMAIN_MARKERS.items():
        scores[domain] = sum(1 for m in marks if m.lower() in blob)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"

def infer_provides(text: str, path: str = "") -> list[str]:
    blob = f"{path}\n{text}"
    out: list[str] = []
    for name, marks in PROVIDES_RULES:
        if any(m in blob for m in marks):
            out.append(name)
    # de-dupe preserve order
    seen = set()
    ordered = []
    for x in out:
        if x not in seen:
            seen.add(x)
            ordered.append(x)
    return ordered

def enrich_meta(meta: dict[str, Any] | None, text: str, path: str = "") -> dict[str, Any]:
    m = dict(meta or {})
    domain = infer_domain(text, path)
    provides = infer_provides(text, path)
    m["domain"] = domain
    if provides and not m.get("provides"):
        m["provides"] = provides
    if domain == "vendor_demo":
        m["exclude"] = True
    return m
