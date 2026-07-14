"""Visible candidate selection and fatal provider error helpers."""
from __future__ import annotations

from typing import Any


FATAL_PROVIDER_MARKERS = (
    "insufficient_quota",
    "exceeded your current quota",
    "invalid_api_key",
    "incorrect api key",
    "authentication_error",
    "unauthorized",
    "forbidden",
    "billing",
)


def is_fatal_provider_error(error: BaseException | str) -> bool:
    text = str(error).lower()
    return any(marker in text for marker in FATAL_PROVIDER_MARKERS)


def normalize_candidates(plan: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Normalize planner candidates and install the selected action.

    New planners return ``candidates`` plus ``selected_index``. Older planners that
    only return ``action`` are represented as a single selected candidate.
    """
    raw = plan.get("candidates", [])
    candidates = [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
    action = plan.get("action")
    if not candidates and isinstance(action, dict):
        candidates = [{"label": "Only proposed action", "action": action}]
    try:
        selected_index = int(plan.get("selected_index", 0))
    except (TypeError, ValueError):
        selected_index = 0
    if not candidates:
        return [], 0
    selected_index = max(0, min(selected_index, len(candidates) - 1))
    selected_action = candidates[selected_index].get("action")
    if isinstance(selected_action, dict):
        plan["action"] = selected_action
    return candidates, selected_index
