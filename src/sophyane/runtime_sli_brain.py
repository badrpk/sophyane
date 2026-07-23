"""SLI Brain Kernel.

SLI owns routing, profile selection, prompt budgeting and fallback behavior.
Unknown language is resolved through a constrained semantic ledger; language
models may explain uncertain terms but may not rewrite frozen user intent.
"""
from __future__ import annotations

import json
import os
import re
import select
import sys
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


def _repository_coding_profile_request(
    message: str,
) -> bool:
    """Return whether a request primarily targets software source."""

    text = " ".join(
        str(message or "").lower().split()
    )

    repository_markers = (
        "src/",
        "src/sophyane",
        "tests/",
        "pytest",
        "python source",
        "python code",
        "source code",
        "repository",
        "codebase",
        "software engineering",
        "software project",
        "project files",
        "git diff",
        "git commit",
        "regression test",
        "test suite",
    )

    coding_actions = (
        "inspect",
        "modify",
        "fix",
        "repair",
        "patch",
        "refactor",
        "implement",
        "improve",
        "update",
        "test",
        "run",
        "compile",
        "debug",
        "maintain",
        "add",
        "remove",
        "write",
        "edit",
        "audit",
    )

    marker_count = sum(
        marker in text
        for marker in repository_markers
    )

    return (
        marker_count >= 2
        or (
            marker_count >= 1
            and any(
                action in text
                for action in coding_actions
            )
        )
    )


def _explicit_browser_program_request(message: str) -> bool:
    """Recognize unambiguous requests to build an interactive browser artifact."""

    text = " ".join(str(message or "").lower().split())

    browser_markers = (
        "browser",
        "website",
        "web app",
        "web page",
        "webpage",
        "html",
    )
    creation_markers = (
        "make",
        "build",
        "create",
        "develop",
        "implement",
        "write",
        "design",
        "program",
        "app",
        "calculator",
        "game",
    )

    return (
        any(marker in text for marker in browser_markers)
        and any(marker in text for marker in creation_markers)
    )


def _profile(message: str) -> str:
    text = message.lower()

    # Repository/source intent outranks visual, website and HTML words.
    # Those words may occur in negations, bug descriptions, file names or
    # acceptance criteria rather than describe the requested deliverable.
    if _repository_coding_profile_request(text):
        return "REPOSITORY_CODING"

    # An explicit request to create a program in the browser is already
    # semantically complete. The word "browser" describes the artifact
    # surface and must not fall through to GENERAL_TASK.
    if _explicit_browser_program_request(text):
        return "WEB_STANDARD"

    if "game" in text or any(
        item in text
        for item in (
            "chess",
            "snake",
            "tetris",
            "tic tac",
            "pong",
            "ping pong",
        )
    ):
        return "GAME_HTML5"

    if any(
        item in text
        for item in (
            "dashboard",
            "admin panel",
            "analytics",
        )
    ):
        return "WEB_DASHBOARD"

    if any(
        item in text
        for item in (
            "shop",
            "store",
            "ecommerce",
            "marketplace",
            "cart",
            "grocery",
            "kiryana",
        )
    ):
        return "WEB_ECOMMERCE"

    if any(
        item in text
        for item in (
            "website",
            "web app",
            "landing page",
            "html",
            "portfolio",
            "site",
        )
    ):
        if any(
            item in text
            for item in (
                "luxury",
                "premium",
                "editorial",
                "cinematic",
                "fancy",
                "beautiful",
            )
        ):
            return "WEB_PREMIUM"

        return "WEB_STANDARD"

    if any(
        item in text
        for item in (
            "android",
            "ios",
            "mobile app",
        )
    ):
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


def _timed_console_input(
    prompt: str,
    *,
    timeout: float = 10.0,
    default: str = "",
) -> tuple[str, bool]:
    """Read one line without allowing HITL to halt SLI indefinitely.

    Returns ``(text, timed_out)``. On terminals without selectable stdin,
    SLI uses the default immediately rather than risking a permanent pause.
    """

    print(prompt, end="", flush=True)

    try:
        if not sys.stdin.isatty():
            print(default, flush=True)
            return default, True

        readable, _, _ = select.select(
            [sys.stdin],
            [],
            [],
            max(0.0, timeout),
        )

        if not readable:
            print(default, flush=True)
            return default, True

        line = sys.stdin.readline()

        if line == "":
            print(default, flush=True)
            return default, True

        return line.rstrip("\r\n"), False

    except (OSError, ValueError):
        # Some mobile shells and redirected terminals cannot select stdin.
        # Autonomy is safer than falling back to indefinite input().
        print(default, flush=True)
        return default, True


def _semantic_steering(
    candidate: str,
    instruction: str,
) -> str:
    instruction = " ".join(
        str(instruction or "").strip().split()
    )

    if not instruction:
        return candidate

    return (
        candidate.rstrip()
        + "\n\nLIVE USER STEERING — incorporate without discarding "
          "non-conflicting approved requirements:\n"
        + instruction
    )


def _confidence_value(ledger: Any) -> float:
    try:
        return float(getattr(ledger, "confidence", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _human_choice_materially_useful(ledger: Any) -> bool:
    """Ask only when SLI has a genuine semantic decision to resolve."""

    uncertain = tuple(
        getattr(ledger, "uncertain_terms", ()) or ()
    )
    confidence = _confidence_value(ledger)

    return bool(uncertain) and confidence < 0.78



def _confirm(self: Any, original: str, *, has_project: bool, tui_v2: Any) -> tuple[str, str] | None:
    # Explicit browser-build requests contain enough deterministic intent
    # to route without asking a provider to reinterpret ordinary words such
    # as "numbers" or "browser".
    if _explicit_browser_program_request(original):
        decision = decide(original, has_project=has_project)
        self.progress(
            f"SLI Brain: {decision.route} / {decision.profile}"
        )
        self.progress(
            "SLI Semantic: explicit browser-program intent resolved "
            "deterministically"
        )
        self.progress(
            "SLI Autonomy: confidence sufficient; continuing without "
            "blocking for approval."
        )
        _record(
            "deterministic_browser_decision",
            decision,
            {
                "original": original,
                "semantic_consulted": False,
                "semantic_confidence": 1.0,
                "uncertain_terms": (),
            },
        )
        return decision.route, decision.refined_request

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
        # High-confidence SLI decisions do not stop for ceremonial
        # approval. HITL is reserved for material uncertainty.
        if not _human_choice_materially_useful(ledger):
            self.progress(
                "SLI Autonomy: confidence sufficient; continuing "
                "without blocking for approval."
            )
            _record(
                "autonomous_approved",
                decision,
                {
                    "semantic_resolutions": ledger.resolutions,
                    "confidence": _confidence_value(ledger),
                },
            )
            return decision.route, decision.refined_request

        print(
            "\nSLI is materially uncertain. You may steer it, "
            "but progress will not halt.",
            flush=True,
        )
        print(
            "\n1. Continue with SLI's preferred interpretation"
            "\n2. Replace or refine the request"
            "\n3. Use the original request without semantic resolution"
            "\n0. Cancel",
            flush=True,
        )
        print(
            "\nType a number or type natural-language steering. "
            "No response in 10 seconds selects option 1.",
            flush=True,
        )

        choice, timed_out = _timed_console_input(
            "Choose [0-3, auto 1 in 10s]: ",
            timeout=10.0,
            default="1",
        )
        choice = choice.strip()

        if timed_out:
            self.progress(
                "SLI Autonomy: no HITL instruction received in "
                "10 seconds; selected its preferred option."
            )

        if choice in {"", "1"}:
            _record(
                "autonomous_timeout_approved"
                if timed_out
                else "human_approved",
                decision,
                {
                    "semantic_resolutions": ledger.resolutions,
                    "confidence": _confidence_value(ledger),
                },
            )
            return decision.route, decision.refined_request

        if choice == "0":
            _record("human_cancelled", decision)
            return None

        if choice == "3":
            original_decision = decide(
                original,
                has_project=has_project,
            )
            _record(
                "original_intent_selected",
                original_decision,
            )
            return (
                original_decision.route,
                original_decision.refined_request,
            )

        if choice == "2":
            edited, edit_timed_out = _timed_console_input(
                "Refine request [auto continue unchanged in 10s]: ",
                timeout=10.0,
                default="",
            )

            if edit_timed_out or not edited.strip():
                self.progress(
                    "SLI Autonomy: refinement window expired; "
                    "continuing with the preferred interpretation."
                )
                return decision.route, decision.refined_request

            candidate = _semantic_steering(
                candidate,
                edited,
            )
            self.progress(
                "SLI HITL: refinement incorporated; semantic "
                "evaluation continues."
            )
            continue

        # Any non-menu text is live semantic steering. This lets
        # users type naturally instead of translating intent into
        # menu numbers.
        candidate = _semantic_steering(
            candidate,
            choice,
        )
        self.progress(
            "SLI HITL: live instruction incorporated; autonomy "
            "continues without restarting the mission."
        )


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
