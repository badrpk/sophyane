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

    # SOPHYANE_CODING_REPAIR_HARNESS_CLASSIFIER_V2
    # Strong non-web software-repair objectives belong to the local
    # harness rather than product/browser acquisition.
    _normalized = " ".join(
        str(message or "")
        .lower()
        .split()
    )

    _web_signals = (
        "website",
        "web page",
        "webpage",
        "web app",
        "landing page",
        "frontend",
        "browser",
        "html",
        "dashboard",
        "canvas",
    )

    _repair_signals = (
        "pytest",
        "jest",
        "test suite",
        "test suites",
        "test failure",
        "tests are authoritative",
        "stack trace",
        "stack traces",
        "traceback",
        "source file",
        "source files",
        "code patch",
        "production code",
        "repair the existing",
        "repair existing",
        "verification failed",
        "verification checks",
        "build turns green",
        "re-run verification",
    )

    _action_signals = (
        "repair",
        "fix",
        "patch",
        "debug",
        "diagnose",
        "run tests",
        "execute local test",
        "re-run",
        "rerun",
    )

    _has_web_signal = any(
        term in _normalized
        for term in _web_signals
    )

    # SOPHYANE_REPAIR_SIGNAL_CONCEPT_DEDUP_V1
    #
    # Count semantic repair concepts, not overlapping literal spellings.
    # Previously "source files" counted both "source file" and
    # "source files", and plural forms such as "test suites" and
    # "stack traces" had the same defect. A generic construction request
    # mentioning source files could therefore satisfy the >=2 repair gate
    # without containing two independent repair signals.
    _repair_signal_groups = (
        ("pytest",),
        ("jest",),
        ("test suite", "test suites"),
        ("test failure",),
        ("tests are authoritative",),
        ("stack trace", "stack traces"),
        ("traceback",),
        ("source file", "source files"),
        ("code patch",),
        ("production code",),
        ("repair the existing", "repair existing"),
        ("verification failed",),
        ("verification checks",),
        ("build turns green",),
        ("re-run verification",),
    )

    _repair_hits = sum(
        1
        for group in _repair_signal_groups
        if any(term in _normalized for term in group)
    )

    _action_hits = sum(
        1
        for term in _action_signals
        if term in _normalized
    )

    if (
        not _has_web_signal
        and (
            _repair_hits >= 2
            or (
                _repair_hits >= 1
                and _action_hits >= 1
            )
        )
    ):
        return True

    # SOPHYANE_HARNESS_SCOPE_GUARD_V1
    #
    # This fast path is deliberately narrower than the general execution
    # policy.  The race harness currently owns bounded repair/test execution,
    # while generic software construction belongs to the normal adaptive race
    # where SLI, local and cloud producers can independently compete.
    #
    # Using broad policy.execution here caused requests such as "build an API"
    # or "generate backend stubs" to enter the Python/TDD harness even though
    # try_coding_request() could not claim them.  The harness then failed
    # deterministically and poisoned subsequent repair rounds.
    #
    # Strong repair requests were returned above.  Everything else must remain
    # available to the ordinary race rather than being captured here.
    return False


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


def _coding_result_report(
    result: object,
) -> str:
    """Serialize local coding capability result for the SLI graph."""
    handled = bool(
        getattr(result, "handled", False)
    )
    ok = bool(
        getattr(result, "ok", False)
    )
    capability = str(
        getattr(result, "capability", "") or ""
    )
    summary = str(
        getattr(result, "summary", "") or ""
    )
    workspace = str(
        getattr(result, "workspace", "") or ""
    )
    error = str(
        getattr(result, "error", "") or ""
    )

    files = list(
        getattr(result, "files", []) or []
    )

    lines = [
        "Sophyane local coding harness",
        f"Handled: {handled}",
        f"Capability: {capability}",
        f"Summary: {summary}",
        f"Workspace: {workspace}",
        f"Files: {', '.join(str(x) for x in files)}",
    ]

    if error:
        lines.append(
            f"Error: {error}"
        )

    lines.append(
        f"Success: {ok}"
    )

    return "\n".join(lines)


def _run_local_coding_via_coi(
    request: str,
    root: Path,
    *,
    progress: Progress,
) -> object | None:
    """Run Sophyane's dedicated coding capability as a bounded COI task.

    COI owns orchestration, permissions and persistent task/run/event traces.
    The coding capability continues to own generation, immutable tests,
    RED/GREEN execution and SVR objective feedback.
    """
    from sophyane.coi import (
        AgentManifest,
        COIOrchestrator,
        TaskContract,
    )
    from sophyane.local_coding_capability import (
        try_coding_request,
    )

    coi = COIOrchestrator()

    permissions = [
        "workspace.read",
        "workspace.write",
        "process.run",
        "validator.pytest",
    ]

    manifest = AgentManifest(
        name="adaptive-python-coding",
        role="coding-validator",
        skills=[
            "python",
            "pytest",
            "adaptive_tdd",
            "red_green",
            "evidence_diagnosis",
            "svr_feedback",
        ],
        permissions=permissions,
        tools=[
            "local_gguf",
            "pytest",
            "sli_svr",
        ],
        # Model selection remains with Sophyane's provider/runtime layer.
        provider="dispatcher",
        max_steps=12,
    )

    result_holder: dict[str, object] = {}

    def runner(
        task: TaskContract,
        context: dict[str, object],
    ) -> dict[str, object]:
        coding_result = try_coding_request(
            task.goal,
            workspace=task.workspace,
            memory_context=context.get(
                "durable_memory"
            ),
        )

        result_holder["coding_result"] = (
            coding_result
        )

        if coding_result is None:
            return {
                "handled": False,
                "ok": False,
                "reason": (
                    "dedicated coding capability "
                    "did not claim request"
                ),
            }

        return {
            "handled": bool(
                coding_result.handled
            ),
            "ok": bool(
                coding_result.ok
            ),
            "capability": str(
                coding_result.capability
            ),
            "summary": str(
                coding_result.summary
            ),
            "files": list(
                coding_result.files
            ),
            "error": str(
                coding_result.error
            ),
            "evidence_count": len(
                coding_result.evidence or []
            ),
        }

    coi.register(
        manifest,
        runner,
    )

    task = TaskContract(
        goal=request,
        owner="sli-harness",
        priority=90,
        workspace=str(root),
        repository=str(
            Path.cwd().resolve()
        ),
        permissions=permissions,
        outputs=[],
        validation=[
            "pytest.red",
            "pytest.green",
            "tests.immutable",
            "evidence.grounded",
            "svr.feedback",
        ],
        timeout_seconds=1200,
    )

    progress(
        f"COI: submitted adaptive coding task {task.task_id}"
    )

    try:
        from sophyane.durable_memory import (
            recall as recall_durable_memory,
        )

        recalled_memory = recall_durable_memory(
            request,
            limit=6,
        )

    except Exception:
        recalled_memory = []

    coi_result = coi.run(
        task,
        agent="adaptive-python-coding",
        context={
            "source": "sli_harness",
            "verification": "objective",
            "durable_memory": recalled_memory,
        },
    )

    progress(
        "COI: adaptive coding run "
        f"ok={coi_result.get('ok')} "
        f"task={task.task_id}"
    )

    try:
        from sophyane.durable_memory import (
            remember_event,
        )

        remember_event(
            "coi.adaptive_coding.completed",
            {
                "task_id": task.task_id,
                "goal": request,
                "ok": bool(
                    coi_result.get("ok")
                ),
                "agent":
                    "adaptive-python-coding",
                "result": coi_result,
            },
            namespace="coi",
        )

    except Exception:
        pass

    coding_result = result_holder.get(
        "coding_result"
    )

    if coding_result is None:
        return None

    # Attach task identity for external diagnostics without changing the
    # immutable CodingResult dataclass.
    try:
        marker = (
            root
            / ".sophyane-coi-task-id"
        )

        marker.write_text(
            task.task_id + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass

    return coding_result


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

    # Explicit coding/TDD requests retain first refusal, but execute through
    # Sophyane COI so orchestration, permissions, task identity, events and
    # local traces remain first-class rather than bypassed.
    try:
        coding_result = _run_local_coding_via_coi(
            request,
            root,
            progress=progress,
        )

        if (
            coding_result is not None
            and getattr(
                coding_result,
                "handled",
                False,
            )
        ):
            progress(
                "SLI harness: COI adaptive coding capability handled request"
            )

            coi_task_id = ""

            try:
                marker = (
                    root
                    / ".sophyane-coi-task-id"
                )

                if marker.exists():
                    coi_task_id = (
                        marker.read_text(
                            encoding="utf-8"
                        ).strip()
                    )
            except Exception:
                pass

            payload = {
                "request": request,
                "workspace": str(root),
                "handled": bool(
                    coding_result.handled
                ),
                "ok": bool(
                    coding_result.ok
                ),
                "capability": str(
                    coding_result.capability
                ),
                "orchestrator": "coi",
                "coi_task_id": coi_task_id,
                "svr_feedback": True,
                "output": str(
                    coding_result.summary
                ),
                "files": list(
                    coding_result.files
                ),
                "error": str(
                    coding_result.error
                ),
                "evidence": [
                    {
                        "command": list(
                            item.command
                        ),
                        "cwd": item.cwd,
                        "exit_code": item.exit_code,
                        "stdout": item.stdout,
                        "stderr": item.stderr,
                        "duration_ms": item.duration_ms,
                        "timed_out": item.timed_out,
                    }
                    for item in (
                        coding_result.evidence
                        or []
                    )
                ],
            }

            _write_report(
                root,
                payload,
            )

            report = _coding_result_report(
                coding_result
            )

            return (
                report
                + "\nOrchestrator: COI"
                + (
                    f"\nCOI task: {coi_task_id}"
                    if coi_task_id
                    else ""
                )
                + "\nSVR feedback: enabled"
            )

    except Exception as error:
        # Coding errors are surfaced, but generic execution can still attempt
        # a compatible deterministic capability. Internet acquisition remains
        # outside this dedicated coding branch.
        progress(
            f"SLI harness COI coding error: {error}"
        )

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
