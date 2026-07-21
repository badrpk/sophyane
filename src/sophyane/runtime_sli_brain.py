"""SLI Brain Kernel v1.

SLI owns routing, profile selection, prompt budgeting and fallback behavior.
Language models are replaceable workers. The kernel is deliberately compact so
small local models remain useful without any cloud API.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BrainDecision:
    route: str
    profile: str
    refined_request: str
    criteria: tuple[str, ...]
    local_prompt_budget: int = 1200


def _state_root() -> Path:
    return Path(os.environ.get("SOPHYANE_HOME", Path.home() / ".local/share/sophyane")).expanduser()


def _clean(text: str, limit: int = 700) -> str:
    return " ".join(str(text or "").strip().split())[:limit]


def _profile(message: str) -> str:
    text = message.lower()
    if "game" in text or any(x in text for x in ("chess", "snake", "tetris", "tic tac")):
        return "GAME_HTML5"
    if any(x in text for x in ("dashboard", "admin panel", "analytics")):
        return "WEB_DASHBOARD"
    if any(x in text for x in ("shop", "store", "ecommerce", "marketplace", "cart")):
        return "WEB_ECOMMERCE"
    if any(x in text for x in ("website", "web app", "landing page", "html", "portfolio")):
        if any(x in text for x in ("luxury", "premium", "editorial", "cinematic", "fancy", "beautiful")):
            return "WEB_PREMIUM"
        return "WEB_STANDARD"
    if any(x in text for x in ("android", "ios", "mobile app")):
        return "MOBILE_APP"
    return "GENERAL_TASK"


def _route(message: str, has_project: bool) -> str:
    text = message.lower()
    if has_project and any(x in text for x in (
        "continue", "update", "improve", "change", "fix", "modify", "add ", "remove ",
        "existing", "above", "same project", "reopen",
    )):
        return "continue_project"
    if re.search(
        r"\b(build|make|create|design|develop|implement|write|fix|repair|patch|run|test|deploy|open|continue|convert|install|integrate|optimi[sz]e|add|remove|change|update|improve|modify)\b",
        text,
    ):
        return "execution"
    return "chat"


def _criteria(profile: str, message: str) -> tuple[str, ...]:
    text = message.lower()
    items: list[str] = []
    if profile.startswith("WEB_") or profile == "GAME_HTML5":
        items.extend((
            "Create real browser artifacts with no missing local assets.",
            "Verify the current page over HTTP before completion.",
        ))
    if profile == "WEB_PREMIUM":
        items.extend((
            "Use meaningful premium content, strong composition, rich sections, and verified relevant imagery.",
            "Include tasteful motion and prefers-reduced-motion support; reject generic placeholder cards.",
        ))
    if profile == "WEB_ECOMMERCE":
        items.append("Include a coherent browse-to-action flow with usable mobile controls.")
    if profile == "WEB_DASHBOARD":
        items.append("Use legible information hierarchy and responsive data presentation.")
    if profile == "GAME_HTML5":
        items.append("Provide working interaction, visible state feedback, and restart behavior.")
    if any(x in text for x in ("phone", "mobile", "responsive", "touch")):
        items.append("Fit 320px-wide screens without overflow and use accessible touch targets.")
    return tuple(items[:5])


def decide(message: str, *, has_project: bool) -> BrainDecision:
    raw = _clean(message)
    profile = _profile(raw)
    route = _route(raw, has_project)
    # SLI creates a safe first interpretation without needing an LLM. The local
    # worker may improve wording, but it may not change this route or profile.
    refined = raw
    if route == "execution" and profile == "WEB_PREMIUM":
        refined = (
            raw.rstrip(".")
            + ". Build a polished mobile-first experience using verified local photography, meaningful sections, "
              "tasteful animations, reduced-motion support, and deterministic asset/browser verification."
        )
    elif route == "execution" and profile.startswith("WEB_"):
        refined = raw.rstrip(".") + ". Produce a responsive, complete, verified browser project with no broken assets."
    return BrainDecision(route, profile, refined, _criteria(profile, raw))


def _compact_refinement_prompt(decision: BrainDecision, *, has_project: bool) -> str:
    criteria = " | ".join(decision.criteria) or "Preserve user intent."
    return (
        "You are a small local wording worker inside the SLI Brain. Do not plan or execute. "
        "Correct spelling and rewrite the request clearly. Keep the SLI route/profile unchanged. "
        "Return compact JSON only: {\"objective\":\"...\",\"selection_reason\":\"route="
        + decision.route
        + " profile="
        + decision.profile
        + "\",\"success_criteria\":[\"...\"],\"action\":{\"type\":\"respond\",\"message\":\"...\"}}. "
        + f"Project active={str(has_project).lower()}. Criteria={criteria}. Request={decision.refined_request[:650]}"
    )[: decision.local_prompt_budget]


def _parse_worker(raw: str, decision: BrainDecision, tui_v2: Any) -> BrainDecision:
    try:
        plan = tui_v2.extract_plan(raw)
    except Exception:
        plan = None
    if not isinstance(plan, dict):
        return decision
    objective = _clean(plan.get("objective") or decision.refined_request)
    if len(objective) < 8:
        objective = decision.refined_request
    criteria = plan.get("success_criteria")
    parsed = tuple(_clean(x, 220) for x in criteria if _clean(x, 220))[:5] if isinstance(criteria, list) else decision.criteria
    return BrainDecision(decision.route, decision.profile, objective, parsed or decision.criteria, decision.local_prompt_budget)


def _record(event: str, decision: BrainDecision, extra: dict[str, Any] | None = None) -> None:
    try:
        path = _state_root() / "sli-brain-events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"ts": time.time(), "event": event, **asdict(decision), **(extra or {})}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _confirm(self: Any, original: str, *, has_project: bool, tui_v2: Any) -> tuple[str, str] | None:
    candidate = original
    while True:
        decision = decide(candidate, has_project=has_project)
        self.progress(f"SLI Brain: {decision.route} / {decision.profile}")
        # Refinement is optional. A local timeout never destroys the SLI route.
        try:
            response = self.call_provider(_compact_refinement_prompt(decision, has_project=has_project), timeout=22)
            decision = _parse_worker(getattr(response, "text", str(response)), decision, tui_v2)
            _record("local_refinement", decision)
        except Exception as error:  # noqa: BLE001
            self.progress(f"SLI Brain kept deterministic intent after local worker failure: {type(error).__name__}")
            _record("deterministic_refinement", decision, {"error": type(error).__name__})

        if decision.route == "chat":
            return "chat", decision.refined_request

        print(f"\nSLI profile: {decision.profile}\n", flush=True)
        print("I understood your request as:\n", flush=True)
        print(decision.refined_request, flush=True)
        if decision.criteria:
            print("\nAcceptance points:", flush=True)
            for item in decision.criteria:
                print(f"- {item}", flush=True)
        print("\n1. Approve and continue\n2. Edit and refine again\n0. Cancel", flush=True)
        try:
            choice = input("Choose [0-2, default 1]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if choice in {"", "1"}:
            _record("approved", decision)
            return decision.route, decision.refined_request
        if choice == "0":
            _record("cancelled", decision)
            return None
        if choice == "2":
            try:
                edited = input("Edit request: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return None
            if edited:
                candidate = edited
            continue
        print("Please choose 0, 1, or 2.", flush=True)


def install_sli_brain() -> None:
    """Install last so SLI owns intent and prompt policy."""
    from sophyane import runtime_intent_refinement_patch as refinement
    from sophyane import tui_v2

    if getattr(refinement, "_sli_brain_installed", False):
        return

    original_context = tui_v2.ObservableTUI._context_prompt

    def context_prompt(self: Any, message: str, *, continuing: bool) -> str:
        decision = decide(message, has_project=continuing)
        base = original_context(self, message, continuing=continuing)
        # Cap inherited conversation/context aggressively for small local models.
        base = _clean(base, 850)
        checks = " | ".join(decision.criteria)
        return (
            f"SLI_PROFILE={decision.profile}; ROUTE={decision.route}; "
            f"GOAL={base}; CHECKS={checks}; "
            "SLI owns decomposition, assets, validation and repair. Return only the next compact executable artifact/action."
        )[:1400]

    refinement._confirm_refinement = _confirm
    tui_v2.ObservableTUI._context_prompt = context_prompt
    refinement._sli_brain_installed = True
