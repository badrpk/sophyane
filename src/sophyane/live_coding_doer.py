"""Live progress reporting for Sophyane's guarded coding runtime.

Progress is deliberately operational rather than private model reasoning: users see
what stage is active, which tool/action is running, and the resulting evidence.
Messages are flushed immediately and normally written to stderr so --agent-json
keeps stdout machine-readable.
"""
from __future__ import annotations

import contextlib
import shlex
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Iterator, TextIO

from sophyane.doer import StepRecord
from sophyane.guarded_coding_doer import GuardedCodingDoerRuntime


class LiveProgressReporter:
    """Emit concise, timestamped, immediately flushed progress events."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        stream: TextIO | None = None,
        heartbeat_seconds: float = 5.0,
    ) -> None:
        self.enabled = enabled
        self.stream = stream or sys.stderr
        self.heartbeat_seconds = max(1.0, float(heartbeat_seconds))
        self.started_at = time.monotonic()
        self._lock = threading.Lock()

    def emit(self, icon: str, message: str) -> None:
        if not self.enabled:
            return
        elapsed = time.monotonic() - self.started_at
        with self._lock:
            print(
                f"[{elapsed:7.1f}s] {icon} {message}",
                file=self.stream,
                flush=True,
            )

    @contextlib.contextmanager
    def waiting(self, icon: str, message: str) -> Iterator[None]:
        """Show an initial status plus periodic heartbeats around blocking calls."""
        if not self.enabled:
            yield
            return
        self.emit(icon, message)
        stop = threading.Event()

        def heartbeat() -> None:
            while not stop.wait(self.heartbeat_seconds):
                self.emit("…", f"Still {message.lower()}")

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=0.2)


class LiveGuardedCodingDoerRuntime(GuardedCodingDoerRuntime):
    """Guarded repository agent with visible planner/tool/verifier activity."""

    def __init__(
        self,
        *args: Any,
        progress: LiveProgressReporter | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.progress = progress or LiveProgressReporter()
        self._visible_step = 0

    @staticmethod
    def _action_summary(action: dict[str, Any]) -> str:
        kind = str(action.get("type", "unknown")).strip().lower()
        if kind in {"write_file", "read_file", "apply_patch", "replace_lines"}:
            return f"{kind}: {action.get('path', '<missing path>')}"
        if kind == "run_command":
            argv = action.get("argv", [])
            if isinstance(argv, str):
                command = argv
            else:
                command = shlex.join(str(item) for item in argv)
            return f"run_command: {command}"
        if kind == "search_repository":
            return f"search_repository: {action.get('query', '')}"
        if kind == "verify_checks":
            checks = action.get("checks", [])
            return f"verify_checks: {len(checks) if isinstance(checks, list) else 0} checks"
        if kind == "git_checkpoint":
            return f"git_checkpoint: {action.get('label', 'checkpoint')}"
        if kind == "create_task_queue":
            tasks = action.get("tasks", [])
            return f"create_task_queue: {len(tasks) if isinstance(tasks, list) else 0} tasks"
        if kind == "batch":
            actions = action.get("actions", [])
            return f"batch: {len(actions) if isinstance(actions, list) else 0} actions"
        return kind

    def _context(self, prompt: str) -> str:
        with self.progress.waiting("🔎", "Indexing repository and retrieving relevant code"):
            context = super()._context(prompt)
        snapshot = self.repository_snapshot
        self.progress.emit(
            "✓",
            f"Repository indexed: {len(snapshot.files)} files, "
            f"{len(snapshot.symbols)} symbols, {len(snapshot.tests)} tests",
        )
        return context

    def _plan(
        self,
        prompt: str,
        context: str,
        objective: str,
        criteria: list[str],
        history: list[StepRecord],
        verifier_instruction: str,
    ) -> dict[str, Any]:
        self._visible_step = len(history) + 1
        with self.progress.waiting(
            "🧠",
            f"Step {self._visible_step}: selecting the best next safe action",
        ):
            plan = super()._plan(
                prompt,
                context,
                objective,
                criteria,
                history,
                verifier_instruction,
            )
        action = plan.get("action", {})
        if isinstance(action, dict):
            self.progress.emit("→", f"Selected {self._action_summary(action)}")
            if str(action.get("type", "")).lower() == "batch":
                children = action.get("actions", [])
                if isinstance(children, list):
                    for position, child in enumerate(children, start=1):
                        if isinstance(child, dict):
                            self.progress.emit(
                                " ",
                                f"Batch {position}/{len(children)}: {self._action_summary(child)}",
                            )
        return plan

    def _execute_one(self, action: dict[str, Any]) -> dict[str, Any]:
        summary = self._action_summary(action)
        self.progress.emit("⚙", f"Executing {summary}")
        started = time.monotonic()
        try:
            observation = super()._execute_one(action)
        except Exception as error:
            self.progress.emit(
                "✗",
                f"{summary} failed after {time.monotonic() - started:.2f}s: "
                f"{type(error).__name__}: {error}",
            )
            raise
        elapsed = time.monotonic() - started
        status = str(observation.get("status", "completed"))
        self.progress.emit("✓", f"{summary} -> {status} ({elapsed:.2f}s)")

        command = observation.get("command")
        if isinstance(command, dict):
            self.progress.emit(
                "↳",
                f"exit={command.get('exit_code')} timeout={command.get('timed_out', False)}",
            )
            stdout = str(command.get("stdout", "")).strip()
            stderr = str(command.get("stderr", "")).strip()
            if stdout:
                preview = stdout[-1200:].replace("\n", " | ")
                self.progress.emit("↳", f"stdout: {preview}")
            if stderr:
                preview = stderr[-1200:].replace("\n", " | ")
                self.progress.emit("↳", f"stderr: {preview}")

        dependency = observation.get("dependency_diagnosis")
        if isinstance(dependency, dict):
            self.progress.emit(
                "📦",
                f"Missing dependency detected: {dependency.get('module', 'unknown')}; "
                f"suggested command: {shlex.join(str(x) for x in dependency.get('suggested_argv', []))}",
            )
        return observation

    def _verify(
        self,
        prompt: str,
        objective: str,
        criteria: list[str],
        history: list[StepRecord],
        observation: dict[str, Any],
    ) -> dict[str, Any]:
        with self.progress.waiting(
            "🧪",
            f"Step {self._visible_step}: checking evidence against the user objective",
        ):
            verdict = super()._verify(
                prompt,
                objective,
                criteria,
                history,
                observation,
            )
        if verdict.get("goal_met"):
            self.progress.emit("✅", "All required evidence is present; objective verified")
        else:
            missing = [str(item) for item in verdict.get("missing_requirements", [])]
            detail = "; ".join(missing[:4]) or "additional work is required"
            self.progress.emit("↻", f"Verification incomplete: {detail}")
            instruction = str(verdict.get("next_instruction", "")).strip()
            if instruction:
                self.progress.emit("→", f"Repair/replan instruction: {instruction[:800]}")
        return verdict

    def run(self, prompt: str):
        self.progress.emit("🚀", f"Starting autonomous run in {Path(self.workspace)}")
        self.progress.emit("🎯", f"Objective: {prompt}")
        result = super().run(prompt)
        self.progress.emit(
            "🏁",
            f"Run finished: goal_met={result.goal_met}, steps={len(result.steps)}, "
            f"reason={result.stopped_reason}",
        )
        return result
