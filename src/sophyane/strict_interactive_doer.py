"""Strict interactive runtime that repairs malformed planner responses before acting."""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from sophyane.decision_visibility import is_fatal_provider_error, normalize_candidates
from sophyane.doer import ProtocolError, StepRecord
from sophyane.interactive_coding_doer import InteractiveCodingDoerRuntime
from sophyane.strict_protocol import parse_and_validate_plan, strict_repair_request


class StrictInteractiveCodingDoerRuntime(InteractiveCodingDoerRuntime):
    """Require schema-valid JSON plans and retry malformed model output locally."""

    def __init__(self, *args: Any, protocol_attempts: int = 3, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.protocol_attempts = max(1, min(int(protocol_attempts), 5))

    def _planner_request(
        self,
        prompt: str,
        context: str,
        objective: str,
        criteria: list[str],
        history: list[StepRecord],
        verifier_instruction: str,
    ) -> dict[str, Any]:
        return {
            "user_request": prompt,
            "persistent_and_repository_context": context,
            "current_objective": objective,
            "current_success_criteria": criteria,
            "previous_steps": [asdict(item) for item in history[-12:]],
            "verifier_instruction": verifier_instruction,
            "workspace": str(self.workspace),
            "task_queue": self.task_queue.to_dict(),
            "git_status": self.git.status(),
            "capabilities": {
                "repository_index": True,
                "symbol_search": True,
                "precise_patch": True,
                "batched_actions": True,
                "mechanical_verification": True,
                "git_checkpoints": True,
                "dependency_diagnostics": True,
                "browser_tools": False,
                "deployment_tools": False,
            },
            "instruction": (
                "Return exactly one JSON object matching the planner schema. Generate 2 or 3 safe candidates "
                "when possible, select the best one yourself, and encode the selected concrete action. "
                "Do not emit markdown, prose, code fences, XML tool tags, <execute_bash>, or <tool_code>."
            ),
        }

    def _show_decision(self, plan: dict[str, Any]) -> None:
        candidates, selected_index = normalize_candidates(plan)
        if not candidates:
            raise ProtocolError("planner returned no candidate or selected action")
        self.progress.emit("☰", f"Choices considered: {len(candidates)}")
        for index, candidate in enumerate(candidates):
            action = candidate.get("action", {})
            label = str(candidate.get("label") or f"Candidate {index + 1}")
            reason = str(candidate.get("reason", "")).strip()
            marker = "★" if index == selected_index else "·"
            summary = self._action_summary(action) if isinstance(action, dict) else "invalid action"
            self.progress.emit(marker, f"{index + 1}. {label}: {summary}" + (f" — {reason}" if reason else ""))
        chosen = candidates[selected_index]
        chosen_label = str(chosen.get("label") or f"Candidate {selected_index + 1}")
        selection_reason = str(plan.get("selection_reason", "")).strip()
        self.progress.emit(
            "✅",
            f"Selected choice {selected_index + 1}: {chosen_label}"
            + (f" — {selection_reason}" if selection_reason else ""),
        )

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
        request = self._planner_request(
            prompt, context, objective, criteria, history, verifier_instruction
        )
        current_prompt = json.dumps(request, ensure_ascii=False)
        last_error: Exception | None = None

        for attempt in range(1, self.protocol_attempts + 1):
            label = (
                f"Step {self._visible_step}: selecting the best next safe action"
                if attempt == 1
                else f"Step {self._visible_step}: repairing planner protocol (attempt {attempt}/{self.protocol_attempts})"
            )
            try:
                with self.progress.waiting("🧠", label):
                    raw = self.backend(current_prompt, self._system("planner"))
                plan = parse_and_validate_plan(raw)
                self._show_decision(plan)
                return plan
            except Exception as error:
                if is_fatal_provider_error(error):
                    raise
                last_error = error
                preview = raw[-1200:].replace("\n", " | ") if "raw" in locals() else "<no response>"
                self.progress.emit(
                    "⚠",
                    f"Planner protocol rejected: {type(error).__name__}: {error}",
                )
                self.progress.emit("↳", f"Invalid response preview: {preview}")
                if attempt < self.protocol_attempts:
                    self.progress.emit("↻", "Requesting strict JSON regeneration automatically")
                    current_prompt = strict_repair_request(
                        request,
                        raw if "raw" in locals() else "",
                        error,
                        attempt + 1,
                    )

        raise ProtocolError(
            f"planner failed strict JSON protocol after {self.protocol_attempts} attempts: {last_error}"
        )
