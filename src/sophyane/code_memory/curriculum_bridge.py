"""Adaptive bridge between coverage curriculum and installed SLI capabilities.

The bridge:
* converts broad curriculum requests into searchable product identities;
* starts weak families with supported seed contracts;
* raises difficulty after validated success;
* reduces difficulty after repeated failure;
* patches repository search queries to use compact semantic identities;
* disables all browser opening for background work.

No local or cloud LLM is used.
"""
from __future__ import annotations

import os
import re
import subprocess
import webbrowser

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BridgeRequest:
    family: str
    level: int
    original: str
    adapted: str
    search_identity: str
    reason: str


# Level 0 requests deliberately match routes already demonstrated by the
# installed deterministic Python-harness composer.
PYTHON_LEVELS: dict[str, tuple[str, ...]] = {
    "python_policy": (
        (
            "Create exactly one Python file named policy_engine.py. "
            "Implement decide_route(metrics: dict) -> str. "
            "Security-sensitive work must never use cloud. "
            "Prefer local below two validator failures. "
            "Allow cloud only after two failures when budget remains."
        ),
        (
            "Create exactly one Python file named rate_policy.py. "
            "Implement decide_rate_action(metrics: dict) -> str. "
            "Return allow, delay or reject deterministically. "
            "Validate missing and negative values."
        ),
        (
            "Create exactly one Python file named feature_policy.py. "
            "Implement evaluate_feature(context: dict, rules: list[dict]) "
            "-> bool. Use deterministic priority ordering and safe defaults."
        ),
    ),

    "python_orchestration": (
        (
            "Create exactly one Python file named retry_controller.py. "
            "Implement execute_with_validation(task, local_runner, "
            "cloud_runner, validator, max_local_attempts=2). "
            "Retry local first and use cloud at most once."
        ),
        (
            "Create exactly one Python file named capability_solver.py. "
            "Implement solve(required, components). Resolve deterministic "
            "dependency closure from provides and requires. Detect impossible "
            "requirements and cycles."
        ),
        (
            "Create exactly one Python file named dependency_scheduler.py. "
            "Implement schedule(tasks: list[dict]) -> list[str]. "
            "Use deterministic topological ordering, detect missing "
            "dependencies and reject cycles."
        ),
    ),

    "python_security": (
        (
            "Create exactly one Python file named sandbox_guard.py. "
            "Implement resolve_safe(root, candidate). Reject traversal, "
            "absolute escape and symlink escape."
        ),
        (
            "Create exactly one Python file named audit_chain.py. "
            "Implement append_event(path, event) and verify_chain(path). "
            "Use canonical JSON, JSON Lines and SHA-256 chaining."
        ),
        (
            "Create exactly one Python file named safe_archive.py. "
            "Implement safe_members(root, names). Reject absolute paths, "
            "traversal, duplicate destinations and path escape."
        ),
    ),

    "api_service": (
        (
            "Create exactly one Python file named health_service.py. "
            "Implement app as a minimal ASGI application. GET /health must "
            "return status 200 and JSON containing status ok."
        ),
        (
            "Create exactly one Python file named task_api.py. "
            "Implement a minimal typed FastAPI application with GET /health "
            "and POST /tasks. Validate the task title and return JSON."
        ),
    ),
}


BROWSER_LEVELS: dict[str, tuple[tuple[str, str], ...]] = {
    "action_game": (
        (
            "pong game",
            (
                "make a complete playable pong browser game in one "
                "self-contained index.html with keyboard controls, score "
                "and restart"
            ),
        ),
        (
            "brick breaker game",
            (
                "make a complete playable brick breaker game in one "
                "self-contained index.html using canvas, collision detection, "
                "score and restart"
            ),
        ),
        (
            "maze game",
            (
                "make a complete playable maze escape game in one "
                "self-contained index.html with keyboard controls and restart"
            ),
        ),
    ),

    "simulation": (
        (
            "spring simulation",
            (
                "make an interactive spring oscillator simulation in one "
                "self-contained index.html with mass, stiffness and damping "
                "controls, pause and reset"
            ),
        ),
        (
            "projectile motion simulation",
            (
                "make an interactive projectile motion simulation in one "
                "self-contained index.html with velocity, angle, gravity, "
                "start, pause and reset controls"
            ),
        ),
    ),

    "crud_application": (
        (
            "student management app",
            (
                "make a self-contained student management browser application "
                "with add, edit, delete, search and localStorage persistence"
            ),
        ),
        (
            "inventory management app",
            (
                "make a self-contained inventory management browser "
                "application with add, edit, delete, filtering and "
                "localStorage persistence"
            ),
        ),
    ),

    "dashboard": (
        (
            "sales dashboard",
            (
                "make a self-contained sales dashboard with sample data, "
                "summary cards, date filtering, sortable table and responsive "
                "layout"
            ),
        ),
        (
            "inventory dashboard",
            (
                "make a self-contained inventory dashboard with sample data, "
                "stock summary, category filters and sortable table"
            ),
        ),
    ),

    "editor": (
        (
            "markdown editor",
            (
                "make a self-contained markdown editor with live preview, "
                "localStorage, clear, export and keyboard shortcuts"
            ),
        ),
        (
            "json editor",
            (
                "make a self-contained JSON editor with formatting, "
                "validation, error feedback, localStorage and export"
            ),
        ),
    ),

    "data_visualization": (
        (
            "sales chart",
            (
                "make a self-contained interactive sales chart explorer with "
                "sample data, filters and responsive SVG or canvas rendering"
            ),
        ),
        (
            "energy usage chart",
            (
                "make a self-contained energy usage chart explorer with "
                "sample monthly data, category filters and responsive layout"
            ),
        ),
    ),

    "form_application": (
        (
            "registration form",
            (
                "make a self-contained customer registration form with live "
                "validation, submit feedback and reset"
            ),
        ),
        (
            "appointment form",
            (
                "make a self-contained appointment booking form with live "
                "validation, date and time selection, submit feedback and reset"
            ),
        ),
    ),

    "language_exercise": (
        (
            "missing word game",
            (
                "make a complete interactive missing word game in one "
                "self-contained index.html with several questions, feedback, "
                "score, next and restart"
            ),
        ),
        (
            "spelling game",
            (
                "make a complete child-friendly spelling game in one "
                "self-contained index.html with feedback, score and restart"
            ),
        ),
    ),
}


def _clamp_level(
    level: int,
    maximum: int,
) -> int:
    return max(
        0,
        min(
            int(level),
            max(0, maximum - 1),
        ),
    )


def family_level(
    *,
    successes: int,
    failure_streak: int,
) -> int:
    """Raise difficulty slowly and back off immediately on repeated failure."""

    level = int(successes) // 2

    if failure_streak >= 1:
        level -= 1

    if failure_streak >= 3:
        level = 0

    return max(0, level)


def adapt_request(
    family: str,
    original: str,
    *,
    successes: int = 0,
    failure_streak: int = 0,
    cursor: int = 0,
) -> BridgeRequest:
    if family in PYTHON_LEVELS:
        choices = PYTHON_LEVELS[family]

        level = _clamp_level(
            family_level(
                successes=successes,
                failure_streak=failure_streak,
            ),
            len(choices),
        )

        index = min(
            len(choices) - 1,
            level,
        )

        adapted = choices[index]

        return BridgeRequest(
            family=family,
            level=level,
            original=original,
            adapted=adapted,
            search_identity="",
            reason="deterministic supported Python contract",
        )

    if family in BROWSER_LEVELS:
        choices = BROWSER_LEVELS[family]

        level = _clamp_level(
            family_level(
                successes=successes,
                failure_streak=failure_streak,
            ),
            len(choices),
        )

        # Rotate within the current/easier range while avoiding large jumps.
        usable = choices[
            : level + 1
        ]

        identity, adapted = usable[
            int(cursor) % len(usable)
        ]

        return BridgeRequest(
            family=family,
            level=level,
            original=original,
            adapted=adapted,
            search_identity=identity,
            reason="compact browser product identity",
        )

    # Informational sites already have a grounded topic composer.
    if family == "informational_site":
        return BridgeRequest(
            family=family,
            level=0,
            original=original,
            adapted=original,
            search_identity="",
            reason="grounded topic composer",
        )

    return BridgeRequest(
        family=family,
        level=0,
        original=original,
        adapted=original,
        search_identity=compact_identity(original),
        reason="generic compact semantic identity",
    )


def compact_identity(
    request: str,
) -> str:
    low = str(request or "").lower()

    replacements = (
        (
            r"\b(sales|inventory|energy|school|hospital|project|student)\b"
            r".*?\bdashboard\b",
            lambda match: (
                match.group(1)
                + " dashboard"
            ),
        ),
        (
            r"\b(student|inventory|contact|task|book|supplier)\b"
            r".*?\b(registry|manager|management)\b",
            lambda match: (
                match.group(1)
                + " management app"
            ),
        ),
        (
            r"\b(spring|projectile|traffic|orbit|population|heat)\b"
            r".*?\b(simulation|simulator)\b",
            lambda match: (
                match.group(1)
                + " simulation"
            ),
        ),
    )

    for pattern, replacement in replacements:
        match = re.search(
            pattern,
            low,
        )

        if match:
            return replacement(
                match
            )

    stop = {
        "a",
        "an",
        "the",
        "make",
        "create",
        "build",
        "complete",
        "interactive",
        "responsive",
        "self",
        "contained",
        "one",
        "index",
        "html",
        "with",
        "using",
        "include",
        "produce",
        "adjustable",
        "parameters",
        "filtering",
        "filters",
        "summary",
        "cards",
        "persistence",
    }

    tokens = [
        token
        for token in re.findall(
            r"[a-z0-9]+",
            low,
        )
        if token not in stop
    ]

    return " ".join(
        tokens[:3]
    )


def install_search_query_patch(
    identity: str,
) -> None:
    """Patch internet acquisition query generation for the current iteration."""

    if not identity:
        return

    try:
        import sophyane.code_memory.internet_acquire as acquire
    except Exception:
        return

    def queries(
        _request: str,
    ) -> list[str]:
        core = compact_identity(
            identity
        ) or identity

        return [
            f'"{core}" in:name',
            f'{core} in:name,description',
            f'{core} html javascript in:name,description',
            f'{core} canvas javascript in:name,description',
        ]

    for name in (
        "build_search_queries",
        "_sli_build_search_queries_v4",
        "_sli_build_search_queries_v5",
        "_sli_search_queries_v4",
    ):
        if hasattr(acquire, name):
            setattr(
                acquire,
                name,
                queries,
            )


def install_background_browser_block() -> None:
    """Disable webbrowser, preview helpers and Windows browser launches."""

    os.environ[
        "SOPHYANE_DISABLE_BROWSER_OPEN"
    ] = "1"

    os.environ[
        "SOPHYANE_NO_AUTO_OPEN"
    ] = "1"

    os.environ[
        "SOPHYANE_BROWSER_PREVIEW"
    ] = "0"

    os.environ[
        "SOPHYANE_CONTINUOUS_AUTO_PREVIEW"
    ] = "0"

    os.environ[
        "BROWSER"
    ] = "/bin/false"

    webbrowser.open = (
        lambda *_args, **_kwargs: False
    )

    webbrowser.open_new = (
        lambda *_args, **_kwargs: False
    )

    webbrowser.open_new_tab = (
        lambda *_args, **_kwargs: False
    )

    try:
        import sophyane.sli_capability_engine as engine

        def no_preview(
            *_args,
            **_kwargs,
        ) -> str:
            return (
                "Background curriculum preview suppressed."
            )

        if hasattr(
            engine,
            "preview_sli_artifact",
        ):
            engine.preview_sli_artifact = (
                no_preview
            )

    except Exception:
        pass

    # Prevent cmd.exe /c start and xdg-open from bypassing webbrowser.
    original_run = subprocess.run

    def safe_run(
        command,
        *args,
        **kwargs,
    ):
        sequence = (
            list(command)
            if isinstance(
                command,
                (list, tuple),
            )
            else [str(command)]
        )

        joined = " ".join(
            str(part).lower()
            for part in sequence
        )

        browser_command = any(
            marker in joined
            for marker in (
                "cmd.exe /c start",
                "xdg-open",
                "sensible-browser",
                "open_browser",
            )
        )

        if browser_command:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="",
                stderr="background browser suppressed",
            )

        return original_run(
            command,
            *args,
            **kwargs,
        )

    subprocess.run = safe_run


__all__ = [
    "BridgeRequest",
    "adapt_request",
    "compact_identity",
    "family_level",
    "install_background_browser_block",
    "install_search_query_patch",
]
