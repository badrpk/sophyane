"""Convert execution traces into source-aware SLI memories."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from sophyane import sli


BROWSER_TERMS = (
    "calculator", "game", "dashboard", "website", "webpage", "html",
    "form", "quiz", "clock", "timer", "converter", "todo", "portfolio",
    "responsive", "mobile app",
)

FAILURE_PATTERNS = (
    ("EMPTY_PROVIDER_RESPONSE", ("empty provider response", "returned no text")),
    ("UNUSABLE_PROVIDER_RESPONSE", ("could not produce a usable artifact", "no usable artifact")),
    ("INVALID_PLAN_SCHEMA", ("invalid schema", "malformed json", "json decode")),
    ("NO_ACTION_RETURNED", ("no action", "premature completion")),
    ("ARTIFACT_VALIDATION_FAILED", ("validation failed", "structural verification failed", "html rejected")),
    ("EXECUTION_ERROR", ("execution error", "command failed", "traceback")),
    ("BOUNDED_REPAIR_EXHAUSTED", ("bounded repair", "stopped after bounded")),
)


def classify_action(request: object) -> str:
    text = str(request or "").lower()
    if any(term in text for term in BROWSER_TERMS):
        return "GENERATE_BROWSER_ARTIFACT"
    return "EXECUTE_STRUCTURED_TASK"


def classify_failure(status: object, result: object, error: object = "") -> str:
    if str(status or "").lower() in {"success", "succeeded", "completed"}:
        return ""
    evidence = f"{result}\n{error}".lower()
    for category, patterns in FAILURE_PATTERNS:
        if any(pattern in evidence for pattern in patterns):
            return category
    return "UNKNOWN_FAILURE"


def _paths(snapshot: object) -> set[str]:
    if not isinstance(snapshot, dict):
        return set()
    paths: set[str] = set()
    for item in snapshot.get("sample", []):
        value = item.get("path", "") if isinstance(item, dict) else item
        if str(value).strip():
            paths.add(str(value).lower())
    return paths


def calculate_quality_reward(
    *,
    status: object,
    result: object,
    error: object = "",
    workspace_before: object = None,
    workspace_after: object = None,
) -> tuple[float, list[str], str]:
    status_text = str(status or "").lower()
    evidence = f"{result}\n{error}".lower()
    new_paths = _paths(workspace_after) - _paths(workspace_before)
    signals: list[str] = []

    if status_text in {"success", "succeeded", "completed"}:
        reward = 0.35
        signals.append("successful_status:+0.35")
        browser_artifact = any(
            path.endswith((".html", ".htm", ".css", ".js", ".jsx", ".tsx", ".vue", ".svelte"))
            for path in (new_paths or _paths(workspace_after))
        )
        if browser_artifact:
            reward += 0.20
            signals.append("artifact_created:+0.20")
        if any(marker in evidence for marker in (
            "passed structural verification", "validation passed",
            "verified current workspace page", "browser artifact passed",
        )):
            reward += 0.20
            signals.append("validation_passed:+0.20")
        if any(marker in evidence for marker in (
            "opening verified browser preview", "served over http",
            "project completed successfully", "http/1.1\" 200",
        )):
            reward += 0.15
            signals.append("runtime_delivery_verified:+0.15")
        if not any(marker in evidence for marker in (
            "traceback", "runtime error", "validation failed", "command failed",
        )):
            reward += 0.10
            signals.append("no_detected_runtime_error:+0.10")
        category = ""
    else:
        reward = -0.35
        signals.append("failed_status:-0.35")
        category = classify_failure(status, result, error)
        penalty = {
            "EMPTY_PROVIDER_RESPONSE": -0.25,
            "UNUSABLE_PROVIDER_RESPONSE": -0.25,
            "INVALID_PLAN_SCHEMA": -0.20,
            "NO_ACTION_RETURNED": -0.20,
            "ARTIFACT_VALIDATION_FAILED": -0.30,
            "EXECUTION_ERROR": -0.35,
            "BOUNDED_REPAIR_EXHAUSTED": -0.15,
            "UNKNOWN_FAILURE": -0.10,
        }.get(category, -0.10)
        reward += penalty
        signals.append(f"{category.lower()}:{penalty:+.2f}")
        if any(marker in evidence for marker in (
            "previous working files were preserved", "stopped safely",
            "execution stopped safely",
        )):
            reward += 0.10
            signals.append("safe_failure_preservation:+0.10")
        if new_paths:
            reward += 0.05
            signals.append("partial_artifact_preserved:+0.05")

    return max(-1.0, min(1.0, reward)), signals, category


def learn_execution(
    *,
    trace_id: str,
    request: str,
    workspace_before: dict[str, Any],
    workspace_after: dict[str, Any],
    status: str,
    reward: float,
    result: str,
    elapsed_seconds: float,
    error: str = "",
) -> dict[str, Any]:
    del reward  # quality is derived from validator evidence, not caller claims.
    action = classify_action(request)
    quality_reward, quality_signals, failure_category = calculate_quality_reward(
        status=status,
        result=result,
        error=error,
        workspace_before=workspace_before,
        workspace_after=workspace_after,
    )
    with sli.connect() as db:
        memory_id = sli.record(
            db,
            request=request,
            state="execution completed",
            action=action,
            result=result,
            reward=quality_reward,
            confidence=1.0 if status.lower() in {"success", "succeeded", "completed"} else 0.8,
            elapsed_seconds=elapsed_seconds,
            source_type="execution",
        )
        sli.store_trace(
            db,
            {
                "trace_id": trace_id,
                "request": request,
                "action": action,
                "status": status,
                "reward": quality_reward,
                "quality_reward": quality_reward,
                "failure_category": failure_category,
                "quality_signals": quality_signals,
                "result": result,
                "elapsed_seconds": elapsed_seconds,
                "workspace_before": workspace_before,
                "workspace_after": workspace_after,
            },
        )
    return {
        "memory_id": memory_id,
        "trace_id": trace_id,
        "action": action,
        "quality_reward": quality_reward,
        "quality_signals": quality_signals,
        "failure_category": failure_category,
    }
