"""Evidence-gated harness orchestration for Sophyane Option 1.

This module routes genuine software execution requests through Sophyane's
existing task policy and unified execution kernel. It deliberately avoids
claiming success without handled execution and inspectable evidence.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from sophyane.harness_task_policy import classify
from sophyane.unified_execution_kernel import execute_request
from sophyane.sli_harness_dashboard import build_and_open_dashboard

Progress = Callable[[str], None]
REPORT_NAME = ".sophyane-harness-report.json"


def is_harness_execution_request(message: str) -> bool:
    """Return True for executable software tasks covered by harness policy."""

    policy = classify(message)
    return bool(policy.execution and not policy.filesystem_only)


def _command_evidence(payload: Any) -> list[dict[str, Any]]:
    """Extract command-level evidence from current kernel result shapes."""

    if not isinstance(payload, dict):
        return []

    rows = payload.get("evidence")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]

    nested = payload.get("data")
    if isinstance(nested, dict):
        rows = nested.get("evidence")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]

    return []


def _failed_commands(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failed = []
    for row in rows:
        code = row.get("exit_code")
        timed_out = bool(row.get("timed_out"))
        if timed_out or (isinstance(code, int) and code != 0):
            failed.append(row)
    return failed


def _write_report(workspace: Path, payload: dict[str, Any]) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / REPORT_NAME).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def run_harness_execution(
    request: str,
    workspace: Path | str,
    *,
    progress: Progress | None = None,
) -> str:
    """Execute one request through the unified kernel with evidence gating."""

    progress = progress or (lambda _message: None)
    root = Path(workspace).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    policy = classify(request)
    if not policy.execution or policy.filesystem_only:
        return (
            "Sophyane Option 1 harness\n"
            "Handled: False\n"
            "Reason: request is not an executable software harness task\n"
            "Success: False"
        )

    progress("SLI harness: policy accepted executable software task")
    progress(
        "SLI harness: compound plan required"
        if policy.compound
        else "SLI harness: bounded single-goal plan"
    )

    result = execute_request(
        request,
        workspace=root,
        metadata={
            "source": "sli_graph",
            "compound": policy.compound,
            "protected_context": policy.protected_context,
            "evidence_required": True,
        },
    )

    if result is None or not result.handled:
        payload = {
            "request": request,
            "workspace": str(root),
            "handled": False,
            "ok": False,
            "policy": {
                "execution": policy.execution,
                "compound": policy.compound,
                "filesystem_only": policy.filesystem_only,
                "protected_context": policy.protected_context,
            },
            "reason": "No registered deterministic kernel capability handled the request.",
        }
        _write_report(root, payload)
        return (
            "Sophyane Option 1 harness\n"
            "Plan: policy classification → unified capability registry → evidence gate\n"
            "Handled: False\n"
            "Reason: no registered deterministic capability handled this request\n"
            f"Evidence file: {REPORT_NAME}\n"
            "Success: False"
        )

    evidence = result.evidence if isinstance(result.evidence, dict) else {}
    commands = _command_evidence(evidence)
    failed = _failed_commands(commands)

    ok = bool(result.ok and result.handled and result.capability and not failed)
    payload = {
        "request": request,
        "workspace": str(root),
        "handled": bool(result.handled),
        "ok": ok,
        "capability": result.capability,
        "kernel_ok": bool(result.ok),
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "duration_ms": round((result.finished_at - result.started_at) * 1000, 2),
        "policy": {
            "execution": policy.execution,
            "compound": policy.compound,
            "filesystem_only": policy.filesystem_only,
            "protected_context": policy.protected_context,
        },
        "command_evidence": commands,
        "failed_commands": failed,
        "raw_evidence": evidence,
        "output": result.output,
    }
    _write_report(root, payload)

    try:
        dashboard_url = build_and_open_dashboard(
            root,
            payload,
        )
        progress(
            f"SLI harness: dashboard={dashboard_url}"
        )
    except Exception as error:
        dashboard_url = ""
        progress(
            f"SLI harness dashboard unavailable: {error}"
        )

    progress(f"SLI harness: capability={result.capability}")
    progress(
        f"SLI harness: evidence commands={len(commands)} failed={len(failed)}"
    )

    lines = [
        "Sophyane Option 1 harness",
        "Plan: policy classification → unified capability registry → guarded execution → evidence gate",
        f"Compound task: {policy.compound}",
        f"Capability: {result.capability}",
        f"Handled: {result.handled}",
        f"Kernel result: {result.ok}",
        f"Command evidence: {len(commands)}",
        f"Failed commands: {len(failed)}",
        f"Evidence file: {REPORT_NAME}",
    ]

    if dashboard_url:
        lines.append(
            f"Visual dashboard: {dashboard_url}"
        )

    if policy.protected_context:
        lines.append("Protected context: preserved")

    lines.append(f"Success: {ok}")
    return "\n".join(lines)


__all__ = ["is_harness_execution_request", "run_harness_execution"]
