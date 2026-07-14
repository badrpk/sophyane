"""Interactive autonomous coding runtime with visible decisions and fail-fast providers."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from sophyane.decision_visibility import is_fatal_provider_error, normalize_candidates
from sophyane.doer import DoerResult, ProtocolError, StepRecord
from sophyane.live_coding_doer import LiveGuardedCodingDoerRuntime


class InteractiveCodingDoerRuntime(LiveGuardedCodingDoerRuntime):
    """Show candidate actions, selection, code previews, and fatal provider blockers."""

    @staticmethod
    def _system(role: str) -> str:
        base = LiveGuardedCodingDoerRuntime._system(role)
        if role.strip().lower() == "planner":
            return base + (
                " Before acting, generate 2 or 3 materially different safe candidate actions when possible, "
                "score them internally by requirement coverage, risk, reversibility and evidence value, then select "
                "the best one yourself. Never ask the user to choose among safe candidates. Return fields: "
                "candidates:[{label:string, action:object, reason:string}], selected_index:integer, "
                "selection_reason:string, and action equal to the selected candidate action."
            )
        return base

    @staticmethod
    def _preview(text: str, limit: int = 3000) -> str:
        value = text.rstrip()
        if len(value) <= limit:
            return value
        return value[:limit] + f"\n... <{len(value) - limit} more characters>"

    def _plan(
        self,
        prompt: str,
        context: str,
        objective: str,
        criteria: list[str],
        history: list[StepRecord],
        verifier_instruction: str,
    ) -> dict[str, Any]:
        plan = super()._plan(
            prompt,
            context,
            objective,
            criteria,
            history,
            verifier_instruction,
        )
        candidates, selected_index = normalize_candidates(plan)
        if candidates:
            self.progress.emit("☰", f"Choices considered: {len(candidates)}")
            for index, candidate in enumerate(candidates):
                action = candidate.get("action", {})
                label = str(candidate.get("label") or f"Candidate {index + 1}")
                reason = str(candidate.get("reason", "")).strip()
                marker = "★" if index == selected_index else "·"
                summary = self._action_summary(action) if isinstance(action, dict) else "invalid action"
                suffix = f" — {reason}" if reason else ""
                self.progress.emit(marker, f"{index + 1}. {label}: {summary}{suffix}")
            selection_reason = str(plan.get("selection_reason", "")).strip()
            chosen = candidates[selected_index]
            chosen_label = str(chosen.get("label") or f"Candidate {selected_index + 1}")
            self.progress.emit(
                "✅",
                f"Selected choice {selected_index + 1}: {chosen_label}"
                + (f" — {selection_reason}" if selection_reason else ""),
            )
        return plan

    def _execute_one(self, action: dict[str, Any]) -> dict[str, Any]:
        kind = str(action.get("type", "")).strip().lower()
        if kind == "write_file":
            self.progress.emit("🧾", f"Code to write: {action.get('path', '<missing path>')}")
            self.progress.emit("│", self._preview(str(action.get("content", ""))))
        elif kind == "apply_patch":
            self.progress.emit("🩹", f"Patch target: {action.get('path', '<missing path>')}")
            self.progress.emit("-", self._preview(str(action.get("old", "")), 1600))
            self.progress.emit("+", self._preview(str(action.get("new", "")), 1600))
        elif kind == "replace_lines":
            self.progress.emit(
                "🩹",
                f"Replacing {action.get('path', '<missing path>')} lines "
                f"{action.get('start_line')}..{action.get('end_line')}",
            )
            self.progress.emit("+", self._preview(str(action.get("content", "")), 2400))
        return super()._execute_one(action)

    def _completed_result(
        self,
        run_id: str,
        objective: str,
        criteria: list[str],
        goal_met: bool,
        final_output: str,
        history: list[StepRecord],
        stopped_reason: str,
    ) -> DoerResult:
        self.repository_snapshot = self.index.build()
        execution = self.executor.report.to_dict()
        execution["repository"] = self.repository_snapshot.to_dict()
        execution["git_checkpoints"] = self.checkpoints
        execution["task_queue"] = self.task_queue.to_dict()
        return DoerResult(
            run_id,
            objective,
            criteria,
            goal_met,
            final_output,
            history,
            execution,
            stopped_reason,
        )

    def run(self, prompt: str) -> DoerResult:
        self._set_execution_contract(prompt)
        self.progress.emit("🚀", f"Starting autonomous run in {Path(self.workspace)}")
        self.progress.emit("🎯", f"Objective: {prompt}")
        run_id = f"doer-{uuid.uuid4().hex[:12]}"
        self.memory.auto_capture(prompt)
        self.memory.record_message("user", prompt)
        context = self._context(prompt)
        objective = ""
        criteria: list[str] = []
        history: list[StepRecord] = []
        verifier_instruction = ""
        stopped_reason = "max_steps_exhausted"
        repeated: dict[str, int] = {}

        for step_number in range(1, self.max_steps + 1):
            action: dict[str, Any] = {"type": "runtime_error"}
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
                observation = {
                    "status": "error",
                    "error": f"{type(error).__name__}: {error}",
                    "repair_required": not is_fatal_provider_error(error),
                }
                if is_fatal_provider_error(error):
                    message = (
                        "Provider unavailable: quota, billing, authentication, or authorization prevents "
                        "the planner from producing choices or code. Configure a working provider/key and rerun."
                    )
                    self.progress.emit("⛔", message)
                    verdict = {
                        "goal_met": False,
                        "confidence": 1,
                        "missing_requirements": [str(error)],
                        "next_instruction": "Configure a working LLM provider or restore quota.",
                        "final_answer": "",
                    }
                    history.append(StepRecord(step_number, action, observation, verdict))
                    stopped_reason = "provider_unavailable"
                    result = self._completed_result(
                        run_id,
                        objective or prompt,
                        criteria,
                        False,
                        message + " Error: " + str(error),
                        history,
                        stopped_reason,
                    )
                    self.memory.record_message("assistant", result.final_output)
                    self.progress.emit(
                        "🏁",
                        f"Run finished: goal_met=False, steps={len(history)}, reason={stopped_reason}",
                    )
                    return result

            if observation.get("status") == "needs_user":
                final_output = str(observation.get("question", "User input is required."))
                stopped_reason = "essential_user_input_required"
                history.append(StepRecord(step_number, action, observation, {"goal_met": False}))
                result = self._completed_result(
                    run_id,
                    objective or prompt,
                    criteria,
                    False,
                    final_output,
                    history,
                    stopped_reason,
                )
                self.progress.emit("🏁", f"Run stopped: {stopped_reason}")
                return result

            try:
                verdict = self._verify(prompt, objective, criteria, history, observation)
            except Exception as error:
                if is_fatal_provider_error(error):
                    message = (
                        "Provider unavailable during verification. The runtime will not waste remaining loops "
                        "retrying a permanent quota/authentication failure."
                    )
                    self.progress.emit("⛔", message)
                    verdict = {
                        "goal_met": False,
                        "confidence": 1,
                        "missing_requirements": [str(error)],
                        "next_instruction": "Configure a working LLM provider or restore quota.",
                        "final_answer": "",
                    }
                    history.append(StepRecord(step_number, action, observation, verdict))
                    stopped_reason = "provider_unavailable"
                    result = self._completed_result(
                        run_id,
                        objective or prompt,
                        criteria,
                        False,
                        message + " Error: " + str(error),
                        history,
                        stopped_reason,
                    )
                    self.memory.record_message("assistant", result.final_output)
                    self.progress.emit(
                        "🏁",
                        f"Run finished: goal_met=False, steps={len(history)}, reason={stopped_reason}",
                    )
                    return result
                verdict = {
                    "goal_met": False,
                    "confidence": 0,
                    "missing_requirements": [f"Verifier failure: {type(error).__name__}: {error}"],
                    "next_instruction": "Repair the protocol response and continue with a concrete safe action.",
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
                result = self._completed_result(
                    run_id,
                    objective,
                    criteria,
                    True,
                    final_output,
                    history,
                    stopped_reason,
                )
                self.progress.emit(
                    "🏁",
                    f"Run finished: goal_met=True, steps={len(history)}, reason={stopped_reason}",
                )
                return result

            next_instruction = str(
                verdict.get("next_instruction", "Continue toward unmet requirements")
            )
            if observation.get("status") == "command_failed":
                command = observation.get("command", {})
                stderr = str(command.get("stderr", "")).strip()
                stdout = str(command.get("stdout", "")).strip()
                diagnostic = stderr or stdout or "command exited non-zero"
                next_instruction = (
                    "AUTOMATIC REPAIR REQUIRED. Inspect this failure, rewrite the faulty workspace file "
                    f"with corrected complete content, then rerun the command: {diagnostic[-4000:]}"
                )
            elif observation.get("status") == "error":
                next_instruction = (
                    "The previous action was rejected or failed. Do not ask for authorization. Choose a "
                    "different concrete safe action that advances the objective. "
                    + str(observation.get("error", ""))
                )
            verifier_instruction = next_instruction

        missing: list[str] = []
        if history:
            missing = [
                str(item)
                for item in history[-1].verification.get("missing_requirements", [])
            ]
        final_output = "Objective not yet verified."
        if missing:
            final_output += " Missing: " + "; ".join(missing)
        self.memory.record_message("assistant", final_output)
        result = self._completed_result(
            run_id,
            objective or prompt,
            criteria,
            False,
            final_output,
            history,
            stopped_reason,
        )
        self.progress.emit(
            "🏁",
            f"Run finished: goal_met=False, steps={len(history)}, reason={stopped_reason}",
        )
        return result
