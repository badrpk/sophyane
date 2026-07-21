"""SLI intent routing for project continuity and direct-response safety.

This controller prevents unrelated requests from mutating the active project. It
is deterministic and dependency-free so it remains reliable on Termux; decisions
are recorded as SLI events for later sequence learning.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class IntentDecision:
    route: str
    confidence: float
    reason: str


_DIRECT_WRITING = re.compile(
    r"^\s*(?:please\s+)?(?:write|draft|compose|make)\s+(?:me\s+)?(?:a\s+|an\s+|the\s+)?"
    r"(?:letter|email|message|application|request|proposal|poem|story|speech|caption|article)\b",
    re.I,
)
_NEW_PRODUCT = re.compile(
    r"^\s*(?:please\s+)?(?:build|create|design|develop|implement|make)\s+"
    r"(?:a\s+|an\s+|the\s+)?(?:new\s+)?"
    r"(?:website|web\s*site|webpage|web\s+app|app|application|game|dashboard|tool|"
    r"calculator|sketch|drawing|logo|icon|poster|api|service|program|software)\b",
    re.I,
)
_CONTINUATION = re.compile(
    r"^\s*(?:add|remove|change|update|improve|fix|repair|patch|modify|replace|style|"
    r"resize|enlarge|reduce|reopen|test|run|continue|resume)\b",
    re.I,
)
_CURRENT_REFERENCES = (
    "this project", "same project", "current project", "existing project", "this app",
    "this website", "this game", "the game", "the website", "the app", "previous output",
    "above", "it in browser", "open it", "test it", "run it", "make it", "its ",
)


def classify_intent(message: str, *, has_project: bool = False) -> IntentDecision:
    """Choose direct response, current-project edit, or independent project."""
    text = " ".join(str(message or "").strip().lower().split())
    if not text:
        return IntentDecision("direct_response", 1.0, "empty request")

    if _DIRECT_WRITING.search(text):
        return IntentDecision("direct_response", 0.99, "writing request does not require project tools")

    explicitly_current = any(marker in text for marker in _CURRENT_REFERENCES)
    if has_project and (explicitly_current or _CONTINUATION.search(text)):
        return IntentDecision("continue_project", 0.96, "request explicitly edits or operates on the active project")

    if _NEW_PRODUCT.search(text):
        return IntentDecision("new_project", 0.98, "request creates an independent product or artifact")

    if has_project and re.match(r"^\s*(?:make|create|build|design|develop|write)\b", text):
        return IntentDecision("new_project", 0.90, "new creation request has no active-project reference")

    return IntentDecision(
        "continue_project" if has_project and explicitly_current else "direct_response",
        0.75,
        "conservative routing protects existing project files",
    )


def record_intent(message: str, decision: IntentDecision, *, has_project: bool) -> None:
    """Append an observable SLI routing event without making execution depend on IO."""
    try:
        base = Path(os.environ.get("SOPHYANE_HOME", Path.home() / ".local/share/sophyane"))
        path = base / "sli-intent-events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": time.time(),
            "message": str(message)[:1000],
            "has_project": bool(has_project),
            **asdict(decision),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass
