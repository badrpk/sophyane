"""Strict structured planner protocol validation and retry helpers."""
from __future__ import annotations

import json
from typing import Any

from sophyane.doer import ProtocolError, _extract_json


REQUIRED_PLAN_FIELDS = ("objective", "success_criteria", "action")


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    missing = [name for name in REQUIRED_PLAN_FIELDS if name not in plan]
    if missing:
        raise ProtocolError("planner JSON missing required fields: " + ", ".join(missing))
    if not isinstance(plan.get("objective"), str) or not plan["objective"].strip():
        raise ProtocolError("planner objective must be a non-empty string")
    criteria = plan.get("success_criteria")
    if not isinstance(criteria, list) or not criteria or not all(isinstance(x, str) and x.strip() for x in criteria):
        raise ProtocolError("planner success_criteria must be a non-empty string array")
    action = plan.get("action")
    if not isinstance(action, dict) or not isinstance(action.get("type"), str) or not action["type"].strip():
        raise ProtocolError("planner action must be an object with a non-empty type")
    candidates = plan.get("candidates")
    if candidates is not None and not isinstance(candidates, list):
        raise ProtocolError("planner candidates must be an array when present")
    return plan


def parse_and_validate_plan(text: str) -> dict[str, Any]:
    return validate_plan(_extract_json(text))


def strict_repair_request(original_request: dict[str, Any], bad_output: str, error: Exception, attempt: int) -> str:
    payload = {
        "protocol_repair": True,
        "attempt": attempt,
        "validation_error": f"{type(error).__name__}: {error}",
        "previous_invalid_output": bad_output[-6000:],
        "original_request": original_request,
        "required_schema": {
            "objective": "non-empty string",
            "success_criteria": ["one or more measurable strings"],
            "candidates": [
                {"label": "string", "action": {"type": "allowed action"}, "reason": "string"}
            ],
            "selected_index": 0,
            "selection_reason": "string",
            "action": {"type": "must equal selected candidate action"},
            "rationale": "string"
        },
        "instruction": (
            "Return exactly one valid JSON object and nothing else. Do not use markdown, prose, XML tool tags, "
            "code fences, <execute_bash>, or <tool_code>. Select and encode a concrete safe action."
        )
    }
    return json.dumps(payload, ensure_ascii=False)
