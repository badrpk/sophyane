"""Goal-driven planner, executor and verifier loop for Sophyane v15."""
from __future__ import annotations

import json
import re
import shlex
import sys
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from sophyane.execution_evidence import WorkspaceExecutor
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
    candidates.extend(
        re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S | re.I)
    )
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
    """Act, inspect evidence, repair failures and continue until verified."""

    SAFE_COMMANDS = {
        "cat", "cut", "du", "find", "git", "grep", "head", "ls", "pwd",
        "python", "python3", Path(sys.executable).name, "ruff", "sort", "tail",
        "test", "wc", "pytest",
    }
    BLOCKED_TOKENS = {
        "rm", "rmdir", "mkfs", "shutdown", "reboot", "poweroff", "halt",
        "dd", "chmod", "chown", "sudo", "su", "kill", "pkill", "killall",
    }
    VALID_ASK_REASONS = {
        "missing_credential",
        "destructive_action",
        "irreversible_external_action",
        "missing_required_value",
        "subjective_preference",
    }
    FALSE_PERMISSION_MARKERS = {
        "authorize", "authorization", "permission", "approve", "approval",
        "5-line", "five-line", "line2", "line3", "line4", "line5",
        "allow spawning", "confirm file", "confirm execution",
    }

    def __init__(
        self,
        backend: Backend,
        memory: MemoryStore,
        workspace: str | Path,
        *,
        max_steps: int = 12,
        timeout_seconds: float = 120.0,
        max_repeated_actions: int = 2,
    ) -> None:
        self.backend = backend
        self.memory = memory
        self.workspace = Path(workspace).expanduser().resolve()
        allowed = set(WorkspaceExecutor.DEFAULT_ALLOWED) | self.SAFE_COMMANDS
        self.executor = WorkspaceExecutor(
            self.workspace,
            allowed_commands=allowed,
            timeout_seconds=timeout_seconds,
        )
        self.max_steps = max(1, min(int(max_steps), 40))
        self.max_repeated_actions = max(1, int(max_repeated_actions))

    @staticmethod
    def _system(role: str) -> str:
        base = (
            "You are part of Sophyane v15, a local autonomous doer. "
            "Return exactly one JSON object and no prose outside JSON. "
            "Workspace file creation, workspace file replacement, approved Python execution, "
            "pytest, and read-only inspection are already authorized by the user. "
            "Never request authorization, a confirmation phrase, or a multi-line permission sequence for them. "
            "Never merely offer choices when evidence supports one best option. "
            "Never claim machine access is unavailable. "
            "Use observations, stdout and stderr to repair failed work automatically. "
            "Ask the user only when autonomous progress is objectively impossible."
        )
        if role == "planner":
            return base + (
                " Define the objective and measurable success criteria, then select exactly one best next action. "
                "Allowed actions: answer, write_file, run_command, ask_user. "
                "write_file may create or replace a workspace-relative file and must contain the complete corrected content. "
                "run_command must use argv as a JSON string array without shell pipes or redirects. "
                "After a command failure, inspect stderr and rewrite the faulty file before rerunning it. "
                "ask_user is valid only with reason_code in: missing_credential, destructive_action, "
                "irreversible_external_action, missing_required_value, subjective_preference; include missing_field and evidence. "
                "Schema: {objective:string, success_criteria:[string], action:{type:string,...}, rationale:string}."
            )
        if role == "verifier":
            return base + (
                " Independently compare every success criterion with observations and execution evidence. "
                "A file-creation or coding task is incomplete until required files exist and required commands/tests exit 0. "
                "If a command failed, quote the useful stderr diagnosis in next_instruction and require a corrective write_file action. "
                "Reject invented permission requirements. Return: "
                "{goal_met:boolean, confidence:number, missing_requirements:[string], next_instruction:string, final_answer:string}."
            )
        return base

    def _context(self, prompt: str) -> str:
        memory = self.memory.format_relevant(prompt)
        recent = self.memory.recent_messages(limit=6)
        conversation = "\n".join(
            f"{item['role']}: {item['content']}" for item in recent
        )
        parts: list[str] = []
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
        request = {
            "user_request": prompt,
            "persistent_context": context,
            "current_objective": objective,
            "current_success_criteria": criteria,
            "previous_steps": [asdict(item) for item in history],
            "verifier_instruction": verifier_instruction,
            "workspace": str(self.workspace),
            "runtime_capabilities": {
                "workspace_writes_pre_authorized": True,
                "safe_commands_pre_authorized": sorted(self.SAFE_COMMANDS),
                "can_replace_files_to_repair_errors": True,
                "must_continue_until_verified": True,
            },
            "instruction": (
                "Select one executable next action. Do not return a menu. "
                "Do not ask permission for workspace writes, Python, pytest, or read-only commands."
            ),
        }
        return _extract_json(
            self.backend(json.dumps(request, ensure_ascii=False), self._system("planner"))
        )

    def _safe_argv(self, argv: list[str]) -> None:
        if not argv or not all(isinstance(item, str) and item for item in argv):
            raise PermissionError("command argv must be a non-empty string array")
        executable = Path(argv[0]).name
        lowered = {Path(item).name.lower() for item in argv}
        if executable.lower() in self.BLOCKED_TOKENS or lowered & self.BLOCKED_TOKENS:
            raise PermissionError(
                "destructive or privileged command requires explicit user approval"
            )
        for item in argv[1:]:
            if item.startswith("/"):
                candidate = Path(item).expanduser().resolve()
                if candidate != self.workspace and self.workspace not in candidate.parents:
                    if executable not in self.SAFE_COMMANDS:
                        raise PermissionError(
                            "write-capable command cannot target outside workspace"
                        )

    def _validate_ask_user(self, action: dict[str, Any]) -> None:
        reason = str(action.get("reason_code", "")).strip().lower()
        question = str(
            action.get("question") or action.get("prompt") or ""
        ).strip()
        lowered = question.lower()
        if any(marker in lowered for marker in self.FALSE_PERMISSION_MARKERS):
            raise PermissionError(
                "unnecessary permission request rejected; workspace writes and safe execution are pre-authorized"
            )
        if reason not in self.VALID_ASK_REASONS:
            raise PermissionError(
                "ask_user rejected: planner must provide a valid essential reason_code"
            )
        if not str(action.get("missing_field", "")).strip():
            raise PermissionError(
                "ask_user rejected: missing_field is required"
            )
        if not str(action.get("evidence", "")).strip():
            raise PermissionError(
                "ask_user rejected: evidence of the blocker is required"
            )

    def _execute(self, action: dict[str, Any]) -> dict[str, Any]:
        kind = str(action.get("type", "")).strip().lower()
        if kind == "answer":
            return {"status": "answered", "text": str(action.get("text", ""))}
        if kind == "ask_user":
            self._validate_ask_user(action)
            question = str(
                action.get("question") or action.get("prompt") or
                "Essential information is required."
            )
            return {
                "status": "needs_user",
                "question": question,
                "reason_code": action.get("reason_code"),
            }
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
            normalized = [str(item) for item in argv]
            self._safe_argv(normalized)
            command = self.executor.run(
                normalized,
                cwd=str(action.get("cwd", ".")),
            )
            status = "executed" if command.exit_code == 0 else "command_failed"
            return {
                "status": status,
                "command": asdict(command),
                "repair_required": command.exit_code != 0 or command.timed_out,
            }
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
            "instruction": (
                "Mark goal_met true only when every criterion is objectively satisfied. "
                "For failed commands, prescribe a concrete repair based on stderr."
            ),
        }
        verdict = _extract_json(
            self.backend(json.dumps(payload, ensure_ascii=False), self._system("verifier"))
        )
        verdict.setdefault("goal_met", False)
        verdict.setdefault("missing_requirements", [])
        verdict.setdefault("next_instruction", "Continue toward unmet requirements")
        verdict.setdefault("final_answer", "")
        return verdict

    @staticmethod
    def _action_signature(action: dict[str, Any]) -> str:
        return json.dumps(action, sort_keys=True, ensure_ascii=False)

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
        repeated: dict[str, int] = {}

        for step_number in range(1, self.max_steps + 1):
            try:
                plan = self._plan(
                    prompt,
                    context,
                    objective,
                    criteria,
                    history,
                    verifier_instruction,
                )
                objective = str(plan.get("objective") or objective or prompt)
                raw_criteria = plan.get("success_criteria") or criteria or [
                    "The user's requested result is delivered and verified."
                ]
                criteria = [str(item) for item in raw_criteria]
                action = plan.get("action")
                if not isinstance(action, dict):
                    raise ProtocolError("planner omitted structured action")
                signature = self._action_signature(action)
                repeated[signature] = repeated.get(signature, 0) + 1
                if repeated[signature] > self.max_repeated_actions:
                    raise ProtocolError(
                        "planner repeated the same ineffective action; choose a different corrective action"
                    )
                observation = self._execute(action)
            except Exception as error:
                action = locals().get("action", {"type": "runtime_error"})
                observation = {
                    "status": "error",
                    "error": f"{type(error).__name__}: {error}",
                    "repair_required": True,
                }

            if observation.get("status") == "needs_user":
                final_output = str(observation.get("question", "User input is required."))
                stopped_reason = "essential_user_input_required"
                history.append(
                    StepRecord(step_number, action, observation, {"goal_met": False})
                )
                break

            try:
                verdict = self._verify(
                    prompt, objective, criteria, history, observation
                )
            except Exception as error:
                verdict = {
                    "goal_met": False,
                    "confidence": 0,
                    "missing_requirements": [
                        f"Verifier failure: {type(error).__name__}: {error}"
                    ],
                    "next_instruction": (
                        "Repair the protocol response and continue with a concrete safe action."
                    ),
                    "final_answer": "",
                }
            history.append(StepRecord(step_number, action, observation, verdict))
            if bool(verdict.get("goal_met")):
                final_output = str(
                    verdict.get("final_answer")
                    or observation.get("text")
                    or "Objective verified as complete."
                )
                stopped_reason = "goal_verified"
                self.memory.record_message("assistant", final_output)
                return DoerResult(
                    run_id,
                    objective,
                    criteria,
                    True,
                    final_output,
                    history,
                    self.executor.report.to_dict(),
                    stopped_reason,
                )

            next_instruction = str(
                verdict.get("next_instruction", "Continue toward unmet requirements")
            )
            if observation.get("status") == "command_failed":
                command = observation.get("command", {})
                stderr = str(command.get("stderr", "")).strip()
                stdout = str(command.get("stdout", "")).strip()
                diagnostic = stderr or stdout or "command exited non-zero"
                next_instruction = (
                    "AUTOMATIC REPAIR REQUIRED. Inspect this failure, rewrite the faulty "
                    f"workspace file with corrected complete content, then rerun the command: {diagnostic[-4000:]}"
                )
            elif observation.get("status") == "error":
                next_instruction = (
                    "The previous action was rejected or failed. Do not ask for authorization. "
                    "Choose a different concrete safe action that advances the objective. "
                    + str(observation.get("error", ""))
                )
            verifier_instruction = next_instruction

        if not final_output:
            missing: list[str] = []
            if history:
                missing = [
                    str(item)
                    for item in history[-1].verification.get(
                        "missing_requirements", []
                    )
                ]
            final_output = "Objective not yet verified."
            if missing:
                final_output += " Missing: " + "; ".join(missing)
        self.memory.record_message("assistant", final_output)
        return DoerResult(
            run_id,
            objective or prompt,
            criteria,
            False,
            final_output,
            history,
            self.executor.report.to_dict(),
            stopped_reason,
        )
