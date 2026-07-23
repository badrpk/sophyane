"""Strict interactive runtime with schema repair and generic artifact fallback."""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from sophyane.decision_visibility import is_fatal_provider_error, normalize_candidates
from sophyane.doer import ProtocolError, StepRecord, _extract_json
from sophyane.interactive_coding_doer import InteractiveCodingDoerRuntime
from sophyane.strict_protocol import parse_and_validate_plan, strict_repair_request


class StrictInteractiveCodingDoerRuntime(InteractiveCodingDoerRuntime):
    """Require valid plans, normalize model mistakes, and trust evidence."""

    def __init__(self, *args: Any, protocol_attempts: int = 3, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.protocol_attempts = max(1, min(int(protocol_attempts), 5))
        self._current_checks: list[dict[str, Any]] = []

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
            "previous_steps": [asdict(item) for item in history[-4:]],
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
                "when possible, select the best one, and encode the selected concrete action. Use action.type. "
                "For run_command use argv as an array. Never copy a natural-language build/create/make request "
                "into run_command argv. Such requests normally require write_file, apply_patch, replace_lines, "
                "or batch. Use only typed deterministic checks: file_exists, contains, command_exit_zero, "
                "stdout_contains, no_uncommitted_changes. Do not emit markdown, prose, code fences, XML tags, "
                "<execute_bash>, or <tool_code>."
            ),
        }

    @staticmethod
    def _mirrors_user_request(prompt: str, action: dict[str, Any]) -> bool:
        if str(action.get("type", "")).strip().lower() != "run_command":
            return False
        argv = [str(item).strip().lower() for item in action.get("argv", [])]
        prompt_tokens = prompt.lower().split()
        return argv == prompt_tokens or " ".join(argv) == " ".join(prompt_tokens)

    def _artifact_fallback_request(
        self,
        prompt: str,
        context: str,
        objective: str,
        criteria: list[str],
        history: list[StepRecord],
        last_error: Exception | None,
    ) -> str:
        payload = {
            "mode": "generic_artifact_generation",
            "user_request": prompt,
            "objective": objective or prompt,
            "success_criteria": criteria,
            "workspace_context": context[-5000:],
            "previous_steps": [asdict(item) for item in history[-3:]],
            "planner_failure": str(last_error or "unknown planner failure"),
            "required_output": {
                "objective": "string",
                "success_criteria": ["measurable requirement"],
                "files": [
                    {
                        "path": "relative/path.ext",
                        "content": "complete file content",
                    }
                ],
                "summary": "short implementation summary",
            },
            "instruction": (
                "Generate the implementation requested by the user. Return one JSON object only. Put complete "
                "source code in files[].content. Use safe relative paths, no absolute paths, no markdown fences, "
                "and no shell commands. Include every file needed for a runnable minimal implementation."
            ),
        }
        return json.dumps(payload, ensure_ascii=False)

    def _plan_from_artifacts(self, raw: str, prompt: str) -> dict[str, Any]:
        data = _extract_json(raw)
        files = data.get("files") if isinstance(data, dict) else None
        if not isinstance(files, list) or not files:
            raise ProtocolError("artifact fallback returned no files")

        actions: list[dict[str, Any]] = []
        checks: list[dict[str, Any]] = []
        for item in files:
            if not isinstance(item, dict):
                raise ProtocolError("artifact file entry must be an object")
            path = str(item.get("path") or "").strip()
            content = item.get("content")
            if (
                not path
                or path.startswith(("/", "~"))
                or ".." in path.replace("\\", "/").split("/")
                or not isinstance(content, str)
            ):
                raise ProtocolError(f"unsafe or incomplete artifact path: {path!r}")
            actions.append({"type": "write_file", "path": path, "content": content})
            checks.append({"type": "file_exists", "path": path})

        action: dict[str, Any]
        if len(actions) == 1:
            action = actions[0]
        else:
            action = {"type": "batch", "actions": actions}
        action["deterministic_checks"] = checks

        raw_criteria = data.get("success_criteria") if isinstance(data, dict) else None
        criteria = (
            [str(item) for item in raw_criteria if str(item).strip()]
            if isinstance(raw_criteria, list)
            else ["The requested implementation files are created in the workspace."]
        )
        objective = str(data.get("objective") or prompt) if isinstance(data, dict) else prompt
        return {
            "objective": objective,
            "success_criteria": criteria,
            "deterministic_checks": checks,
            "candidates": [
                {
                    "label": "LLM-generated implementation bundle",
                    "action": action,
                    "reason": "The active provider generated complete files after strict planner recovery failed.",
                }
            ],
            "selected_index": 0,
            "selection_reason": "Use provider-generated artifacts and verify them mechanically.",
            "action": action,
            "rationale": str(data.get("summary") or "Generic artifact fallback") if isinstance(data, dict) else "Generic artifact fallback",
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
        request = self._planner_request(prompt, context, objective, criteria, history, verifier_instruction)
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
                action = plan.get("action", {})
                if isinstance(action, dict) and self._mirrors_user_request(prompt, action):
                    raise ProtocolError(
                        "run_command mirrors the natural-language request instead of implementing it"
                    )
                self._current_checks = list(plan.get("deterministic_checks", []))
                self._show_decision(plan)
                return plan
            except Exception as error:
                if is_fatal_provider_error(error):
                    raise
                last_error = error
                preview = raw[-1200:].replace("\n", " | ") if "raw" in locals() else "<no response>"
                self.progress.emit("⚠", f"Planner protocol rejected: {type(error).__name__}: {error}")
                self.progress.emit("↳", f"Invalid response preview: {preview}")
                if attempt < self.protocol_attempts:
                    raw_text = raw if "raw" in locals() else ""
                    resolver_markers = (
                        '"resolved_terms"',
                        '"confidence"',
                        '"material_change"',
                        "constrained semantic resolver",
                        '"uncertain_terms"',
                    )
                    resolver_shaped = (
                        '"resolved_terms"' in raw_text
                        and any(marker in raw_text for marker in resolver_markers[1:])
                    )

                    if resolver_shaped:
                        self.progress.emit(
                            "↻",
                            "Semantic-resolver output detected; resetting planner context",
                        )
                        current_prompt = json.dumps(
                            {
                                "planner_reset": True,
                                "instruction": (
                                    "You are now the execution planner, not a semantic resolver. "
                                    "Ignore every previous semantic-resolver schema. "
                                    "Return exactly one compact JSON object with objective, "
                                    "success_criteria and action. Do not return resolved_terms, "
                                    "confidence, material_change or uncertain_terms."
                                ),
                                "required_schema": {
                                    "objective": "non-empty string",
                                    "success_criteria": ["measurable requirement"],
                                    "action": {
                                        "type": "write_file",
                                        "path": "relative/file.py",
                                        "content": "complete file content",
                                    },
                                },
                                "execution_request": request,
                            },
                            ensure_ascii=False,
                        )
                    else:
                        self.progress.emit(
                            "↻",
                            "Requesting strict JSON regeneration automatically",
                        )
                        current_prompt = strict_repair_request(
                            request,
                            raw_text,
                            error,
                            attempt + 1,
                        )

        self.progress.emit("↻", "Strict planning failed; requesting a generic implementation bundle")
        artifact_prompt = self._artifact_fallback_request(
            prompt, context, objective, criteria, history, last_error
        )
        try:
            with self.progress.waiting("🧩", "Generating implementation files from the active LLM"):
                raw = self.backend(artifact_prompt, self._system("planner"))
            plan = self._plan_from_artifacts(raw, prompt)
            self._current_checks = list(plan.get("deterministic_checks", []))
            self._show_decision(plan)
            return plan
        except Exception as error:
            if is_fatal_provider_error(error):
                raise
            raise ProtocolError(
                "planner and generic artifact generation both failed: "
                f"planner={last_error}; artifacts={type(error).__name__}: {error}"
            ) from error

    def _verify(
        self,
        prompt: str,
        objective: str,
        criteria: list[str],
        history: list[StepRecord],
        observation: dict[str, Any],
    ) -> dict[str, Any]:
        observation = dict(observation)
        if self._current_checks:
            observation["deterministic_checks"] = self._current_checks

        mechanical = (
            self.mechanical.verify(
                self._current_checks,
                command_observations=[asdict(item) for item in self.executor.report.commands],
            )
            if self._current_checks
            else {"passed": None, "results": []}
        )

        try:
            verdict = super()._verify(
                prompt, objective, criteria, history, observation
            )
        except Exception as error:
            verdict = {
                "goal_met": False,
                "confidence": 0,
                "missing_requirements": [
                    f"Verifier failure: {type(error).__name__}: {error}"
                ],
                "next_instruction": "Repair the verifier response and continue with a concrete safe action.",
                "final_answer": "",
            }

        if not isinstance(verdict, dict):
            verdict = {
                "goal_met": False,
                "confidence": 0,
                "missing_requirements": [
                    "Verifier returned an invalid non-dictionary result."
                ],
                "next_instruction": "Repair the verifier response and continue with a concrete safe action.",
                "final_answer": "",
            }

        verdict["mechanical_verification"] = mechanical
        if mechanical.get("passed") is True and self._execution_contract_satisfied():
            verdict.update(
                {
                    "goal_met": True,
                    "confidence": 1,
                    "missing_requirements": [],
                    "next_instruction": "",
                    "final_answer": verdict.get("final_answer")
                    or "Objective completed with verified execution evidence.",
                    "verification_mode": "deterministic_evidence_override",
                }
            )
        return verdict
