"""Hard execution-contract guards for Sophyane's repository coding agent."""
from __future__ import annotations

import re
from typing import Any

from sophyane.v16_doer import CodingDoerRuntime, StepRecord


class GuardedCodingDoerRuntime(CodingDoerRuntime):
    """Prevent prose, menus, and fake permission requests from escaping the loop."""

    MUTATION_TERMS = re.compile(
        r"\b(apply|patch|edit|modify|change|fix|repair|create|write|implement|build|"
        r"refactor|add|remove|rename|update)\b",
        re.I,
    )
    EXECUTION_TERMS = re.compile(
        r"\b(run|execute|test|pytest|lint|verify|compile|build|check)\b",
        re.I,
    )
    MENU_TERMS = re.compile(
        r"(?:\bchoose\b|\bwhich\b|\bconfirm\b|\bpermission\b|\bauthori[sz]e\b|"
        r"\boption\b|\bA/B/C\b|\([ABC]\)|(?:^|\n)\s*[ABC][.)])",
        re.I,
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._active_prompt = ""
        self._requires_mutation = False
        self._requires_command = False

    def _set_execution_contract(self, prompt: str) -> None:
        self._active_prompt = prompt
        self._requires_mutation = bool(self.MUTATION_TERMS.search(prompt))
        self._requires_command = bool(self.EXECUTION_TERMS.search(prompt))

    def _evidence_state(self) -> dict[str, bool]:
        files = bool(self.executor.report.files)
        successful_commands = any(
            command.exit_code == 0 and not command.timed_out
            for command in self.executor.report.commands
        )
        return {
            "file_evidence": files,
            "successful_command_evidence": successful_commands,
        }

    def _execution_contract_satisfied(self) -> bool:
        evidence = self._evidence_state()
        if self._requires_mutation and not evidence["file_evidence"]:
            return False
        if self._requires_command and not evidence["successful_command_evidence"]:
            return False
        return True

    def _guard_action(self, action: dict[str, Any]) -> None:
        kind = str(action.get("type", "")).strip().lower()
        if kind == "answer" and (self._requires_mutation or self._requires_command):
            text = str(action.get("text", ""))
            if not self._execution_contract_satisfied():
                detail = "menu/permission prose" if self.MENU_TERMS.search(text) else "prose-only response"
                raise RuntimeError(
                    "prose-only action rejected for an execution-required objective "
                    f"({detail}); select and perform the best concrete safe action instead"
                )
        if kind == "ask_user" and (self._requires_mutation or self._requires_command):
            question = str(action.get("question") or action.get("prompt") or "")
            reason = str(action.get("reason_code", "")).strip().lower()
            if reason not in {
                "missing_credential",
                "destructive_action",
                "irreversible_external_action",
                "missing_required_value",
                "subjective_preference",
            } or self.MENU_TERMS.search(question):
                raise RuntimeError(
                    "unnecessary choice or permission request rejected; choose the best safe action and continue"
                )

    def _execute_one(self, action: dict[str, Any]) -> dict[str, Any]:
        self._guard_action(action)
        return super()._execute_one(action)

    def _execute(self, action: dict[str, Any]) -> dict[str, Any]:
        self._guard_action(action)
        return super()._execute(action)

    def _verify(
        self,
        prompt: str,
        objective: str,
        criteria: list[str],
        history: list[StepRecord],
        observation: dict[str, Any],
    ) -> dict[str, Any]:
        verdict = super()._verify(prompt, objective, criteria, history, observation)
        evidence = self._evidence_state()
        missing: list[str] = []
        if self._requires_mutation and not evidence["file_evidence"]:
            missing.append("No file creation or patch evidence exists")
        if self._requires_command and not evidence["successful_command_evidence"]:
            missing.append("No successful command or test execution evidence exists")
        if missing:
            verdict["goal_met"] = False
            existing = [str(item) for item in verdict.get("missing_requirements", [])]
            verdict["missing_requirements"] = existing + missing
            verdict["next_instruction"] = (
                "Do not present choices or ask permission for safe workspace actions. "
                "Select the best concrete action, execute it, inspect the evidence, and continue until all requirements are met."
            )
            verdict["final_answer"] = ""
        return verdict

    def run(self, prompt: str):
        self._set_execution_contract(prompt)
        return super().run(prompt)
