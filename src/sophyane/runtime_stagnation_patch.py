"""Progress-aware structured execution loop for long agentic builds."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _is_inspection(action: dict[str, Any]) -> bool:
    kind = str(action.get("type") or "").lower()
    if kind not in {"run", "shell", "run_command", "bash"}:
        return False
    command = " ".join(str(action.get("command") or action.get("cmd") or action.get("content") or "").split())
    patterns = (
        r"^(?:ls|find|cat|head|tail|pwd)\b",
        r"^python3?\s+-c\s+.*(?:listdir|os\.walk|open\().*$",
    )
    return any(re.search(pattern, command) for pattern in patterns)


def _force_progress_prompt(workspace: Path, original_request: str, evidence: list[str], reason: str) -> str:
    files = []
    if workspace.exists():
        files = [str(path.relative_to(workspace)) for path in workspace.rglob("*") if path.is_file()][:30]
    return (
        "The execution is STAGNATING. Do not inspect, list, cat, find, head, tail, or restate the plan. "
        "Take one concrete progress action now: write_file/append_file for a required module, run_command to compile/test, "
        "open_browser for a completed web demo, or respond if the requested increment is already verified. "
        "Return exactly one compact JSON object with top-level action.type and all required fields. Use relative paths only.\n\n"
        f"Reason: {reason}\nWorkspace: {workspace}\nFiles already present: {files}\n"
        f"Original request: {original_request}\nRecent evidence:\n" + "\n".join(evidence[-5:])
    )


def install_stagnation_patch() -> None:
    from sophyane import execution_runtime as runtime

    if getattr(runtime, "_stagnation_patch_installed", False):
        return

    def run_structured_loop(
        *,
        initial_text: str,
        original_request: str,
        ask: Any,
        workspace: Path | None = None,
        max_steps: int = 12,
        progress: Any = None,
    ) -> str:
        workspace = (workspace or Path.cwd()).resolve()
        progress = progress or (lambda _message: None)
        current = initial_text
        evidence: list[str] = []
        recovery_attempts = 0
        consecutive_inspections = 0
        mutations = 0
        step = 1

        while step <= max_steps:
            plan = runtime.extract_plan(current)
            if not plan:
                recovery_attempts += 1
                if recovery_attempts <= 3:
                    reason = "truncated JSON" if runtime.looks_like_truncated_plan(current) else "non-executable response"
                    progress(f"Forcing concrete action after {reason} ({recovery_attempts}/3)")
                    response = ask(_force_progress_prompt(workspace, original_request, evidence, reason))
                    current = getattr(response, "text", str(response))
                    continue
                return "Execution stopped safely after repeated non-executable responses.\n\n" + "\n".join(evidence)

            action = runtime.selected_action(plan)
            if not action:
                recovery_attempts += 1
                if recovery_attempts <= 3:
                    progress(f"Forcing concrete action after missing schema ({recovery_attempts}/3)")
                    response = ask(_force_progress_prompt(workspace, original_request, evidence, "missing or empty action schema"))
                    current = getattr(response, "text", str(response))
                    continue
                return "Execution stopped safely: provider repeatedly returned no executable action.\n\n" + "\n".join(evidence)

            kind = str(action.get("type") or "").lower()
            inspection = _is_inspection(action)
            if inspection and consecutive_inspections >= 1:
                evidence.append(f"Step {step}: Equivalent inspection skipped to preserve action budget.")
                progress(f"Step {step}/{max_steps}: inspection loop detected; forcing progress")
                response = ask(_force_progress_prompt(workspace, original_request, evidence, "repeated inspection without file or test progress"))
                current = getattr(response, "text", str(response))
                recovery_attempts = 0
                consecutive_inspections += 1
                step += 1
                continue

            progress(f"Step {step}/{max_steps}: preparing {kind or 'action'}")
            try:
                ok, result = runtime.execute_action(action, workspace, progress)
            except Exception as error:  # noqa: BLE001
                ok, result = False, f"Action failed safely: {error}"
            evidence.append(f"Step {step}: {result}")

            if not ok:
                recovery_attempts += 1
                if recovery_attempts <= 3:
                    progress(f"Forcing corrected action ({recovery_attempts}/3)")
                    response = ask(_force_progress_prompt(workspace, original_request, evidence, result[:400]))
                    current = getattr(response, "text", str(response))
                    continue
                return "Execution stopped safely.\n\n" + "\n".join(evidence)

            if kind in {"respond", "message", "open_browser", "browser"}:
                return (result or str(action.get("message") or "")) + "\n\nExecution evidence:\n" + "\n".join(evidence)

            if inspection:
                consecutive_inspections += 1
            else:
                consecutive_inspections = 0
                mutations += 1
                recovery_attempts = 0

            followup = (
                "Continue the SAME task in the SAME workspace. Return exactly one compact executable JSON action. "
                "Do not repeat inspections already represented in the execution result. Prefer a concrete file change or compile/test. "
                "Use relative paths. Use append_file for continuation chunks. Finish with respond when this increment is verified.\n\n"
                f"Workspace: {workspace}\nOriginal request: {original_request}\n"
                f"Progress mutations so far: {mutations}\nLatest execution result:\n{result}"
            )
            progress(f"Step {step}/{max_steps}: asking model for next action")
            response = ask(followup)
            current = getattr(response, "text", str(response))
            step += 1

        return "Stopped after bounded execution loop.\n\n" + "\n".join(evidence)

    runtime.run_structured_loop = run_structured_loop
    runtime._stagnation_patch_installed = True
