"""Goal-driven planner, executor and verifier loop for Sophyane v14."""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from sophyane.execution_evidence import ExecutionReport, WorkspaceExecutor
from sophyane.memory import MemoryStore

Backend = Callable[[str, str], str]


@dataclass
class StepRecord:
    step: int
    action: dict[str, Any]
    observation: dict[str, Any]
    verification: dict[str, Any]


@dataclass
class DoerResult:
    run_id: str
    objective: str
    success_criteria: list[str]
    goal_met: bool
    final_output: str
    steps: list[StepRecord] = field(default_factory=list)
    execution: dict[str, Any] = field(default_factory=dict)
    stopped_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "objective": self.objective,
            "success_criteria": self.success_criteria,
            "goal_met": self.goal_met,
            "final_output": self.final_output,
            "steps": [asdict(item) for item in self.steps],
            "execution": self.execution,
            "stopped_reason": self.stopped_reason,
        }


class ProtocolError(RuntimeError):
    pass


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    candidates = [text]
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S | re.I)
    candidates.extend(fenced)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ProtocolError("LLM did not return a valid JSON object")


class DoerRuntime:
    """Continue acting until an independent verifier confirms the objective."""

    READ_ONLY_COMMANDS = {
        "cat", "cut", "du", "find", "git", "grep", "head", "ls", "pwd",
        "python", "python3", Path(sys.executable).name, "ruff", "sort", "tail",
        "test", "wc", "pytest",
    }
    BLOCKED_TOKENS = {
        "rm", "rmdir", "mkfs", "shutdown", "reboot", "poweroff", "halt",
        "dd", "chmod", "chown", "sudo", "su", "kill", "pkill", "killall",
    }

    def __init__(
        self,
        backend: Backend,
        memory: MemoryStore,
        workspace: str | Path,
        *,
        max_steps: int = 12,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.backend = backend
        self.memory = memory
        self.workspace = Path(workspace).expanduser().resolve()
        allowed = set(WorkspaceExecutor.DEFAULT_ALLOWED) | self.READ_ONLY_COMMANDS
        self.executor = WorkspaceExecutor(
            self.workspace,
            allowed_commands=allowed,
            timeout_seconds=timeout_seconds,
        )
        self.max_steps = max(1, min(int(max_steps), 40))

    @staticmethod
    def _system(role: str) -> str:
        base = (
            "You are part of Sophyane v14, a local goal-driven doer. "
            "Return exactly one JSON object and no prose outside JSON. "
            "Never merely offer choices when one option can be selected from evidence. "
            "Never claim machine access is unavailable: the runtime can write files and run approved commands. "
            "Ask the user only when preference, credentials, destructive action, or missing essential information makes autonomous progress impossible."
        )
        if role == "planner":
            return base + (
                " Define the objective and measurable success criteria, then select exactly one best next action. "
                "Allowed action types: answer, write_file, run_command, ask_user. "
                "For run_command use argv as a JSON string array; do not use shell pipes or redirects. "
                "For write_file provide a workspace-relative path and full content. "
                "Schema: {objective:string, success_criteria:[string], action:{type:string,...}, rationale:string}."
            )
        if role == "verifier":
            return base + (
                " Independently compare the user's objective and every success criterion with observations and execution evidence. "
                "Do not accept unsupported textual claims. Return: "
                "{goal_met:boolean, confidence:number, missing_requirements:[string], next_instruction:string, final_answer:string}."
            )
        return base

    def _context(self, prompt: str) -> str:
        memory = self.memory.format_relevant(prompt)
        recent = self.memory.recent_messages(limit=6)
        conversation = "\n".join(
            f"{item['role']}: {item['content']}" for item in recent
        )
        parts = []
        if memory:
            parts.append(memory)
        if conversation:
            parts.append("Recent persistent conversation:\n" + conversation)
        return "\n\n".join(parts)

    def _plan(
        self,
        prompt: str,
        context: str,
        objective: str,
        criteria: list[str],
        history: list[StepRecord],
        verifier_instruction: str,
    ) -> dict[str, Any]:
        history_json = [asdict(item) for item in history]
        request = {
            "user_request": prompt,
            "persistent_context": context,
            "current_objective": objective,
            "current_success_criteria": criteria,
            "previous_steps": history_json,
            "verifier_instruction": verifier_instruction,
            "workspace": str(self.workspace),
            "instruction": "Select the single best action that maximizes verified completion. Do not return a menu of options.",
        }
        return _extract_json(self.backend(json.dumps(request, ensure_ascii=False), self._system("planner")))

    def _safe_argv(self, argv: list[str]) -> None:
        if not argv or not all(isinstance(item, str) and item for item in argv):
            raise PermissionError("command argv must be a non-empty string array")
        executable = Path(argv[0]).name
        lowered = {Path(item).name.lower() for item in argv}
        if executable.lower() in self.BLOCKED_TOKENS or lowered & self.BLOCKED_TOKENS:
            raise PermissionError("destructive or privileged command requires explicit user approval")
        for item in argv[1:]:
            if item.startswith("/"):
                candidate = Path(item).expanduser().resolve()
                if candidate != self.workspace and self.workspace not in candidate.parents:
                    if executable not in self.READ_ONLY_COMMANDS:
                        raise PermissionError("write-capable command cannot target outside workspace")

    def _execute(self, action: dict[str, Any]) -> dict[str, Any]:
        kind = str(action.get("type", "")).strip().lower()
        if kind == "answer":
            return {"status": "answered", "text": str(action.get("text", ""))}
        if kind == "ask_user":
            return {"status": "needs_user", "question": str(action.get("question", "Essential information is required."))}
        if kind == "write_file":
            path = str(action.get("path", "")).strip()
            content = str(action.get("content", ""))
            if not path:
                raise ValueError("write_file requires path")
            evidence = self.executor.write_text(path, content)
            return {"status": "written", "file": asdict(evidence)}
        if kind == "run_command":
            argv = action.get("argv")
            if isinstance(argv, str):
                argv = shlex.split(argv)
            if not isinstance(argv, list):
                raise ValueError("run_command requires argv array")
            argv = [str(item) for item in argv]
            self._safe_argv(argv)
            command = self.executor.run(argv, cwd=str(action.get("cwd", ".")))
            return {"status": "executed", "command": asdict(command)}
        raise ValueError(f"unsupported action type: {kind or '<missing>'}")

    def _verify(
        self,
        prompt: str,
        objective: str,
        criteria: list[str],
        history: list[StepRecord],
        observation: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "user_request": prompt,
            "objective": objective,
            "success_criteria": criteria,
            "prior_steps": [asdict(item) for item in history],
            "latest_observation": observation,
            "execution_report": self.executor.report.to_dict(),
            "instruction": "Mark goal_met true only when every criterion is objectively satisfied. Otherwise state the best next instruction.",
        }
        verdict = _extract_json(self.backend(json.dumps(payload, ensure_ascii=False), self._system("verifier")))
        verdict.setdefault("goal_met", False)
        verdict.setdefault("missing_requirements", [])
        verdict.setdefault("next_instruction", "Continue toward unmet requirements")
        verdict.setdefault("final_answer", "")
        return verdict

    def run(self, prompt: str) -> DoerResult:
        run_id = f"doer-{uuid.uuid4().hex[:12]}"
        self.memory.auto_capture(prompt)
        self.memory.record_message("user", prompt)
        context = self._context(prompt)
        objective = ""
        criteria: list[str] = []
        history: list[StepRecord] = []
        verifier_instruction = ""
        final_output = ""
        stopped_reason = "max_steps_exhausted"

        for step_number in range(1, self.max_steps + 1):
            try:
                plan = self._plan(
                    prompt, context, objective, criteria, history, verifier_instruction
                )
                objective = str(plan.get("objective") or objective or prompt)
                raw_criteria = plan.get("success_criteria") or criteria or ["The user's requested result is delivered and verified."]
                criteria = [str(item) for item in raw_criteria]
                action = plan.get("action")
                if not isinstance(action, dict):
                    raise ProtocolError("planner omitted structured action")
                observation = self._execute(action)
            except Exception as error:
                action = {"type": "runtime_error"}
                observation = {
                    "status": "error",
                    "error": f"{type(error).__name__}: {error}",
                }

            if observation.get("status") == "needs_user":
                final_output = str(observation.get("question", "User input is required."))
                stopped_reason = "essential_user_input_required"
                history.append(StepRecord(step_number, action, observation, {"goal_met": False}))
                break

            try:
                verdict = self._verify(prompt, objective, criteria, history, observation)
            except Exception as error:
                verdict = {
                    "goal_met": False,
                    "confidence": 0,
                    "missing_requirements": [f"Verifier failure: {type(error).__name__}: {error}"],
                    "next_instruction": "Repair the protocol response and continue.",
                    "final_answer": "",
                }
            history.append(StepRecord(step_number, action, observation, verdict))
            if bool(verdict.get("goal_met")):
                final_output = str(verdict.get("final_answer") or observation.get("text") or "Objective verified as complete.")
                stopped_reason = "goal_verified"
                self.memory.record_message("assistant", final_output)
                return DoerResult(
                    run_id, objective, criteria, True, final_output, history,
                    self.executor.report.to_dict(), stopped_reason,
                )
            verifier_instruction = str(verdict.get("next_instruction", "Continue"))

        if not final_output:
            missing: list[str] = []
            if history:
                missing = [str(item) for item in history[-1].verification.get("missing_requirements", [])]
            final_output = "Objective not yet verified."
            if missing:
                final_output += " Missing: " + "; ".join(missing)
        self.memory.record_message("assistant", final_output)
        return DoerResult(
            run_id, objective or prompt, criteria, False, final_output, history,
            self.executor.report.to_dict(), stopped_reason,
        )
