"""Strict structured planner protocol validation and retry helpers."""
from __future__ import annotations

import json
import shlex
from typing import Any

from sophyane.doer import ProtocolError, _extract_json


REQUIRED_PLAN_FIELDS = ("objective", "success_criteria", "action")
SUPPORTED_CHECKS = {
    "file_exists", "contains", "command_exit_zero", "stdout_contains",
    "no_uncommitted_changes",
}


def _normalize_check(check: Any) -> dict[str, Any] | None:
    if not isinstance(check, dict):
        return None
    normalized = dict(check)
    kind = str(normalized.get("type", "")).strip().lower()
    if kind in SUPPORTED_CHECKS:
        normalized["type"] = kind
        return normalized
    command = str(normalized.get("command", "")).strip()
    if command:
        try:
            tokens = shlex.split(command)
        except ValueError:
            tokens = []
        if len(tokens) >= 4 and tokens[0] == "grep" and "-q" in tokens and tokens[-1] == "stdout":
            index = tokens.index("-q") + 1
            if index < len(tokens) - 1:
                return {"type": "stdout_contains", "text": tokens[index]}
        if normalized.get("expected_exit_code") == 0 and tokens:
            return {"type": "command_exit_zero", "executable": tokens[0].rsplit("/", 1)[-1]}
    return None


def _normalize_checks(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [item for check in raw if (item := _normalize_check(check)) is not None]


def _normalize_action(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    action = dict(raw)
    if not action.get("type") and isinstance(action.get("action"), str):
        action["type"] = action.pop("action")
    kind = str(action.get("type", "")).strip().lower()
    action["type"] = kind
    if kind == "run_command" and not isinstance(action.get("argv"), list):
        command = action.pop("command", "")
        if isinstance(command, str) and command.strip():
            try:
                action["argv"] = shlex.split(command)
            except ValueError as error:
                raise ProtocolError(f"invalid run_command string: {error}") from error
    if kind == "batch" and isinstance(action.get("actions"), list):
        action["actions"] = [_normalize_action(item) for item in action["actions"]]
    checks = _normalize_checks(action.get("deterministic_checks"))
    if checks:
        action["deterministic_checks"] = checks
    else:
        action.pop("deterministic_checks", None)
    return action


def _coerce_action_only_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Normalize recoverable small-model action responses into a strict plan.

    Some compact local models return either:

        {"action": "write_file", "path": "...", "content": "..."}

    or:

        {"action": {"type": "write_file", ...}}

    without repeating the planner objective and success criteria. Preserve the
    proposed action, add only conservative metadata, and let the normal strict
    validator and deterministic execution checks decide whether it is usable.
    """
    if not isinstance(plan, dict):
        return plan

    normalized = dict(plan)

    # Flat action form:
    # {"action": "write_file", "path": "...", "content": "..."}
    flat_kind = normalized.get("action")
    if isinstance(flat_kind, str) and flat_kind.strip():
        action = {
            key: value
            for key, value in normalized.items()
            if key not in {
                "objective",
                "success_criteria",
                "deterministic_checks",
                "candidates",
                "selected_index",
                "selection_reason",
                "rationale",
            }
        }
        action["type"] = action.pop("action").strip().lower()

        normalized = {
            key: value
            for key, value in normalized.items()
            if key in {
                "objective",
                "success_criteria",
                "deterministic_checks",
                "candidates",
                "selected_index",
                "selection_reason",
                "rationale",
            }
        }
        normalized["action"] = action

    # Alternate flat form:
    # {"type": "write_file", "path": "...", "content": "..."}
    elif (
        not isinstance(normalized.get("action"), dict)
        and isinstance(normalized.get("type"), str)
        and normalized["type"].strip()
    ):
        action = {
            key: value
            for key, value in normalized.items()
            if key not in {
                "objective",
                "success_criteria",
                "deterministic_checks",
                "candidates",
                "selected_index",
                "selection_reason",
                "rationale",
            }
        }

        normalized = {
            key: value
            for key, value in normalized.items()
            if key in {
                "objective",
                "success_criteria",
                "deterministic_checks",
                "candidates",
                "selected_index",
                "selection_reason",
                "rationale",
            }
        }
        normalized["action"] = action

    action = normalized.get("action")
    if isinstance(action, dict) and (
        isinstance(action.get("type"), str)
        or isinstance(action.get("action"), str)
    ):
        if not isinstance(normalized.get("objective"), str) or not normalized["objective"].strip():
            normalized["objective"] = "Execute the requested workspace action."

        criteria = normalized.get("success_criteria")
        if not isinstance(criteria, list) or not any(
            isinstance(item, str) and item.strip() for item in criteria
        ):
            normalized["success_criteria"] = [
                "The proposed workspace action executes successfully.",
                "Deterministic validation confirms progress toward the user objective.",
            ]

        normalized.setdefault(
            "selection_reason",
            "Recovered a concrete action from a compact local-model response.",
        )

    return normalized


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    plan = _coerce_action_only_plan(plan)

    missing = [name for name in REQUIRED_PLAN_FIELDS if name not in plan]
    if missing:
        raise ProtocolError("planner JSON missing required fields: " + ", ".join(missing))
    if not isinstance(plan.get("objective"), str) or not plan["objective"].strip():
        raise ProtocolError("planner objective must be a non-empty string")
    criteria = plan.get("success_criteria")
    if not isinstance(criteria, list) or not criteria or not all(
        isinstance(item, str) and item.strip() for item in criteria
    ):
        raise ProtocolError("planner success_criteria must be a non-empty string array")
    plan["action"] = _normalize_action(plan.get("action"))
    action = plan["action"]
    if not isinstance(action.get("type"), str) or not action["type"].strip():
        raise ProtocolError("planner action must be an object with a non-empty type")
    if action["type"] == "run_command" and not isinstance(action.get("argv"), list):
        raise ProtocolError("run_command requires argv array")
    top_checks = _normalize_checks(plan.get("deterministic_checks"))
    action_checks = _normalize_checks(action.get("deterministic_checks"))
    merged = top_checks + [item for item in action_checks if item not in top_checks]
    plan["deterministic_checks"] = merged
    if merged:
        action["deterministic_checks"] = merged
    candidates = plan.get("candidates")
    if candidates is not None:
        if not isinstance(candidates, list):
            raise ProtocolError("planner candidates must be an array when present")
        for candidate in candidates:
            if isinstance(candidate, dict):
                candidate["action"] = _normalize_action(candidate.get("action"))
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
            "deterministic_checks": [{"type": "stdout_contains", "text": "expected text"}],
            "candidates": [{"label": "string", "action": {"type": "allowed action"}, "reason": "string"}],
            "selected_index": 0,
            "selection_reason": "string",
            "action": {"type": "run_command", "argv": ["python", "-m", "pytest", "-q"]},
            "rationale": "string",
        },
        "instruction": (
            "Return exactly one valid JSON object and nothing else. Use action.type, never action.action. "
            "For run_command use argv as an array, never a shell command string. Use only typed deterministic "
            "checks: file_exists, contains, command_exit_zero, stdout_contains, no_uncommitted_changes. "
            "Do not use markdown, prose, XML tool tags, code fences, <execute_bash>, or <tool_code>."
        ),
    }
    return json.dumps(payload, ensure_ascii=False)
