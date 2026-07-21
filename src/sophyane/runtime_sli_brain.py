"""SLI Brain Kernel.

SLI owns routing, profile selection, prompt budgeting and fallback behavior.
Unknown language is resolved through a constrained semantic ledger; language
models may explain uncertain terms but may not rewrite frozen user intent.
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
    if "game" in text or any(x in text for x in ("chess", "snake", "tetris", "tic tac", "pong", "ping pong")):
        return "GAME_HTML5"
    if any(x in text for x in ("dashboard", "admin panel", "analytics")):
        return "WEB_DASHBOARD"
    if any(x in text for x in ("shop", "store", "ecommerce", "marketplace", "cart", "grocery", "kiryana")):
        return "WEB_ECOMMERCE"
    if any(x in text for x in ("website", "web app", "landing page", "html", "portfolio", "site")):
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
        items.append("Provide working interaction, visible state feedback, safe controls, and restart behavior.")
    if any(x in text for x in ("phone", "mobile", "responsive", "touch", "android")):
        items.append("Fit 320px-wide screens without overflow and use accessible touch targets.")
    return tuple(items[:5])


def decide(message: str, *, has_project: bool) -> BrainDecision:
    raw = _clean(message)
    profile = _profile(raw)
    route = _route(raw, has_project)
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
    from sophyane.runtime_sli_semantic import resolve

    candidate = original
    while True:
        # Semantic consultation is narrow: known anchors remain frozen and only
        # unknown terms are offered to the active model. If the model fails or
        # drifts, SLI falls back to its own normalized ledger.
        ledger = resolve(candidate, self.call_provider, timeout=18)
        decision = decide(ledger.normalized, has_project=has_project)
        self.progress(f"SLI Brain: {decision.route} / {decision.profile}")
        if ledger.uncertain_terms:
            state = "drift rejected" if ledger.drift_rejected else "bounded consultation complete"
            self.progress(f"SLI Semantic: {state}; uncertain={', '.join(ledger.uncertain_terms[:6])}")
        _record(
            "semantic_decision",
            decision,
            {
                "original": ledger.original,
                "normalized": ledger.normalized,
                "anchors": ledger.anchors,
                "uncertain_terms": ledger.uncertain_terms,
                "resolutions": ledger.resolutions,
                "semantic_confidence": ledger.confidence,
                "semantic_consulted": ledger.consulted,
                "semantic_drift_rejected": ledger.drift_rejected,
            },
        )

        if decision.route == "chat":
            return "chat", decision.refined_request

        print(f"\nSLI profile: {decision.profile}\n", flush=True)
        print("I understood your request as:\n", flush=True)
        print(decision.refined_request, flush=True)
        if ledger.resolutions:
            print("\nSemantic resolutions:", flush=True)
            for source, meaning in ledger.resolutions:
                print(f"- {source} → {meaning}", flush=True)
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
            _record("approved", decision, {"semantic_resolutions": ledger.resolutions})
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
        base = _clean(original_context(self, message, continuing=continuing), 850)
        checks = " | ".join(decision.criteria)
        return (
            f"SLI_PROFILE={decision.profile}; ROUTE={decision.route}; "
            f"GOAL={base}; CHECKS={checks}; "
            "The approved SLI intent ledger is immutable. Do not broaden scope or alter names, locations, artifact type, or user constraints. "
            "SLI owns decomposition, assets, validation and repair. Return only the next compact executable artifact/action."
        )[:1600]

    refinement._confirm_refinement = _confirm
    tui_v2.ObservableTUI._context_prompt = context_prompt
    refinement._sli_brain_installed = True
