"""Inject SLI execution experience before intent refinement and planning."""
from __future__ import annotations

import json
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any


def _state_root() -> Path:
    return Path(os.environ.get("SOPHYANE_HOME", Path.home() / ".local/share/sophyane")).expanduser()


def _recent_events(limit: int = 40) -> list[dict[str, Any]]:
    path = _state_root() / "sli-provider-events.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    except Exception:
        return []
    events: list[dict[str, Any]] = []
    for line in lines:
        try:
            value = json.loads(line)
        except Exception:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def _task_hints(message: str) -> list[str]:
    text = str(message or "").lower()
    hints: list[str] = []
    browser = any(word in text for word in ("website", "web app", "browser", "html", "landing page"))
    game = "game" in text or any(word in text for word in ("chess", "snake", "tetris", "tic tac"))
    mobile = any(word in text for word in ("phone", "mobile", "responsive", "touch"))
    if browser:
        hints.extend([
            "Prefer one complete index.html with inline CSS and JavaScript, plus a local assets folder when rich photography materially improves the demo.",
            "For visual subjects, use several relevant high-resolution royalty-free photographs from reputable sources, download them into the workspace, and reference the local copies rather than fragile hotlinks.",
            "Aim for a premium showcase that looks more polished than a basic production MVP: strong hero composition, editorial typography, layered cards, gradients, depth, and intentional whitespace.",
            "Include tasteful motion such as entrance reveals, hover depth, subtle parallax or floating accents, smooth transitions, and micro-interactions; also respect prefers-reduced-motion.",
            "Avoid placeholders, generic labels, missing assets, undeclared fonts, and repetitive cards with only headings and one sentence.",
            "Require structural validation, local-asset verification, responsive checks, and an HTTP-verified browser preview before completion.",
        ])
    if mobile:
        hints.append("Use responsive sizing, readable touch targets, fluid typography, and layouts that fit narrow screens without overflow.")
    if game:
        hints.extend([
            "Require working interaction logic, visible state or score feedback, and a restart path.",
            "Verify JavaScript completeness and interaction handlers before opening the demo.",
        ])
    if any(word in text for word in ("fix", "update", "improve", "change", "existing", "above")):
        hints.append("Preserve working project behavior and modify the current workspace rather than rebuilding unrelated files.")
    return hints


def sli_preplanning_feedback(message: str) -> str:
    """Return concise, evidence-led advice for the first LLM refinement call."""
    events = _recent_events()
    defects = Counter()
    actions = Counter()
    latencies: list[float] = []
    for event in events:
        action = str(event.get("action") or "").strip()
        if action:
            actions[action] += 1
        for defect in event.get("defects") or []:
            defects[str(defect)] += 1
        try:
            latencies.append(float(event.get("latency_seconds", 0.0)))
        except (TypeError, ValueError):
            pass

    lines = _task_hints(message)
    if defects:
        common = ", ".join(name for name, _count in defects.most_common(4))
        lines.append(f"Recent SLI execution history most often observed these failure modes: {common}.")
    if actions:
        total = sum(actions.values())
        rescue = actions.get("escalate_cloud", 0)
        repair = actions.get("targeted_repair", 0)
        if total and (rescue or repair):
            lines.append(
                f"Across {total} recent SLI decisions, {repair} needed targeted repair and {rescue} needed cloud rescue; "
                "make acceptance criteria concrete enough to prevent those repairs where possible."
            )
    if latencies:
        average = sum(latencies) / len(latencies)
        lines.append(f"Recent provider latency averaged {average:.1f}s; prefer a direct, bounded plan with minimal redundant generations.")
    if not lines:
        lines.append("Use a small, testable plan; create real artifacts before commands; verify every user-visible requirement.")
    return "\n".join(f"- {line}" for line in lines[:10])


def _record_onset(message: str, feedback: str) -> None:
    try:
        path = _state_root() / "sli-onset-events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        event = {"ts": time.time(), "request": message[:600], "feedback": feedback[:2400]}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass


def install_sli_onset_feedback() -> None:
    """Make SLI advice part of refinement and the approved planning prompt."""
    from sophyane import adaptive_execution
    from sophyane import runtime_intent_refinement_patch as refinement
    from sophyane import tui_v2

    if getattr(refinement, "_sli_onset_feedback_installed", False):
        return

    original_prompt = refinement._refinement_prompt
    original_context = tui_v2.ObservableTUI._context_prompt
    original_html_prompt = adaptive_execution._raw_html_prompt

    def refinement_prompt(message: str, *, has_project: bool) -> str:
        feedback = sli_preplanning_feedback(message)
        _record_onset(message, feedback)
        return (
            original_prompt(message, has_project=has_project)
            + "\n\nSLI PRE-PLANNING FEEDBACK (execution experience, not a user request):\n"
            + feedback
            + "\nAmalgamate the raw request with only the relevant SLI feedback. The objective shown for user confirmation "
              "must be the highest-success interpretation, while preserving the user's actual goal and avoiding unrelated scope."
        )

    def context_prompt(self: Any, message: str, *, continuing: bool) -> str:
        base = original_context(self, message, continuing=continuing)
        feedback = sli_preplanning_feedback(message)
        return (
            base
            + "\n\nSLI EXECUTION GUIDANCE FOR THIS PLAN:\n"
            + feedback
            + "\nLay out the smallest plan predicted to satisfy the approved request, while targeting a premium visual demo rather than a bare minimum page."
        )

    def premium_html_prompt(original_request: str, existing: str = "") -> str:
        base = original_html_prompt(original_request, existing)
        return (
            base
            + "\nPREMIUM DEMO QUALITY GATE: Build a visually exceptional, portfolio-grade experience rather than a plain template. "
              "Use relevant high-resolution royalty-free photography when appropriate; download chosen photos into assets/images and use local relative paths. "
              "Add a cinematic hero, richer sections, clear navigation, authentic copy, polished calls-to-action, layered depth, and fancy but tasteful animations. "
              "Include scroll reveals, hover micro-interactions, smooth transitions, and prefers-reduced-motion support. "
              "Do not use lorem ipsum, generic Plant 1 labels, broken URLs, or external hotlinks in the final HTML."
        )

    refinement._refinement_prompt = refinement_prompt
    tui_v2.ObservableTUI._context_prompt = context_prompt
    adaptive_execution._raw_html_prompt = premium_html_prompt
    refinement._sli_onset_feedback_installed = True
