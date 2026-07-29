
"""Execution recovery helpers shared by current and older Sophyane TUIs."""
from __future__ import annotations

from sophyane.environment_constraints import (
    constraint_for_command,
    learn_constraints_from_result,
)

import hashlib
import time
import uuid
from pathlib import Path
from typing import Any


def _snapshot(root: Path) -> dict[str, str]:
    output: dict[str, str] = {}
    if not root.exists():
        return output
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            output[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError):
            continue
    return output


def install_orchestration_patch() -> None:
    from sophyane import execution_runtime as runtime

    if getattr(runtime, "_orchestration_installed", False):
        return

    try:
        from sophyane import tui_v2
    except ImportError:
        tui_v2 = None

    if tui_v2 is not None and hasattr(tui_v2, "_execution_requested"):
        original_execution_requested = tui_v2._execution_requested

        def execution_requested(message: str) -> bool:
            # Explicit imperative requests take precedence over a mistaken native
            # chat classification. This keeps requests such as "Create index.html"
            # inside the validated execution runtime.
            text = " ".join(message.lower().split())
            if original_execution_requested(message):
                return True
            try:
                from sophyane.native_kernel import classify
                native_mode = classify(message)
            except Exception:  # noqa: BLE001
                native_mode = None
            if native_mode == "execution":
                return True
            if native_mode == "chat":
                return False
            extra = (
                "diagnose", "debug", "giving error", "has error", "error in", "repair",
                "optimize", "profile", "audit", "integrate", "simulate", "benchmark",
                "self-improvement", "self improvement", "start a persistent", "monitor",
                "implement", "demonstrate", "apply reductions", "re-test", "retest",
            )
            return any(marker in text for marker in extra)

        tui_v2._execution_requested = execution_requested

        original_loop = tui_v2.run_structured_loop

        def learning_loop(
            *,
            initial_text: str,
            original_request: str,
            ask: Any,
            workspace: Path,
            max_steps: int,
            progress: Any,
        ) -> str:
            from sophyane.sli_learner import learn_execution
            from sophyane.sli_schema import ensure_current_schema

            before = _snapshot(workspace)
            started = time.monotonic()
            trace_id = uuid.uuid4().hex[:12]
            result = original_loop(
                initial_text=initial_text,
                original_request=original_request,
                ask=ask,
                workspace=workspace,
                max_steps=max_steps,
                progress=progress,
            )
            lowered = str(result).lower()
            failed = (
                lowered.startswith("execution loop failed")
                or lowered.startswith("stopped after bounded")
                or "failed safely" in lowered
            )
            try:
                ensure_current_schema()
                learned = learn_execution(
                    trace_id=trace_id,
                    request=original_request,
                    workspace_before=before,
                    workspace_after=_snapshot(workspace),
                    status="failed" if failed else "succeeded",
                    reward=-1.0 if failed else 1.0,
                    result=str(result),
                    elapsed_seconds=time.monotonic() - started,
                )
                progress(
                    "SLI recorded interactive execution "
                    f"{trace_id} reward={float(learned.get('quality_reward', 0.0)):+.2f}"
                )
            except Exception as error:  # noqa: BLE001
                progress(f"SLI recording skipped safely: {type(error).__name__}: {error}")
            return result

        tui_v2.run_structured_loop = learning_loop

    original_execute = runtime.execute_action

    def execute_action(action: dict[str, Any], workspace: Path, progress: Any) -> tuple[bool, str]:
        normalized = runtime._normalize_action(action) or action
        kind = str(normalized.get("type") or "").strip().lower()

        if kind in {"write_file", "append_file"}:
            path = str(normalized.get("path") or normalized.get("file") or "").strip()
            if not path:
                return False, "File action rejected: missing path. Return a concrete relative filename inside the workspace."
            target = (workspace / path).resolve()
            root = workspace.resolve()
            if target != root and root not in target.parents:
                return False, f"File action rejected: {path} is outside the active workspace. Use a relative path in {workspace}."

            content = str(
                normalized.get("content")
                or normalized.get("text")
                or ""
            )

            # Repair provider output that contains literal backslash-n text
            # rather than actual line breaks.
            if "\\n" in content and "\n" not in content:
                content = (
                    content
                    .replace("\\r\\n", "\n")
                    .replace("\\n", "\n")
                    .replace("\\t", "\t")
                )
                normalized = dict(normalized)
                normalized["content"] = content
                progress(f"Decoded escaped line breaks for {path}")

            if kind == "write_file" and target.exists():
                existing = target.read_text(
                    encoding="utf-8",
                    errors="replace",
                )

                if content == existing:
                    return True, (
                        f"File already matches requested content: {path} "
                        f"({target.stat().st_size} bytes)."
                    )

                # write_file is replacement, never an inferred continuation.
                temporary = target.with_name(
                    target.name + ".sophyane.tmp"
                )
                temporary.write_text(content, encoding="utf-8")
                temporary.replace(target)

                progress(
                    f"Atomically replaced {target} "
                    f"({len(existing)} -> {len(content)} characters)"
                )
                return True, (
                    f"Atomically replaced {target} "
                    f"({target.stat().st_size} total bytes)."
                )


        if kind in {"run", "shell", "run_command", "bash", "run_interactive", "interactive", "play_demo"}:
            command = str(normalized.get("command") or normalized.get("cmd") or normalized.get("content") or "").strip()
            if not command:
                return False, "Command action rejected: missing command. Return a concrete command or respond with completion."

            known_constraint = constraint_for_command(workspace, command)
            if known_constraint:
                return False, known_constraint

        try:
            ok, result = original_execute(normalized, workspace, progress)
        except (ValueError, OSError) as error:
            return False, f"Action rejected safely: {error}"

        if kind in {
            "run",
            "shell",
            "run_command",
            "bash",
            "run_interactive",
            "interactive",
            "play_demo",
        }:
            learn_constraints_from_result(
                workspace,
                command,
                result,
            )

        if not ok and result.startswith(
            "Repeated command blocked:"
        ):
            return False, (
                result
                + ". A repeated command is not proof of success. "
                  "Repair the project or run a distinct verification."
            )

        if not ok and result.startswith(
            "Repeated write_file blocked"
        ):
            return False, (
                result
                + ". Return a complete write_file replacement or an "
                  "explicit append_file continuation."
            )

        return ok, result

    runtime.execute_action = execute_action
    runtime._orchestration_installed = True
