"""Strict interactive runtime with schema repair and generic artifact fallback."""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sophyane.decision_visibility import is_fatal_provider_error, normalize_candidates
from sophyane.doer import ProtocolError, StepRecord, _extract_json
from sophyane.interactive_coding_doer import InteractiveCodingDoerRuntime
from sophyane.strict_protocol import parse_and_validate_plan, strict_repair_request
from sophyane.local_chunking import decompose_request, merge_chunk_artifacts, parse_chunk_artifact


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
            "workspace_context": context,
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
            "local_chunks": [
                {
                    "id": chunk.id,
                    "title": chunk.title,
                    "instruction": chunk.instruction,
                    "depends_on": list(chunk.depends_on),
                }
                for chunk in decompose_request(prompt)
            ],
            "instruction": (
                "Generate the implementation requested by the user in the listed bounded chunks. Return one JSON "
                "object only. Put complete source code in files[].content. Use safe relative paths, no absolute "
                "paths, no markdown fences, and no shell commands. Keep each chunk small and independently valid. "
                "Do not emit conflicting writes to the same path; use operation=append only when necessary."
            ),
        }
        return json.dumps(payload, ensure_ascii=False)

    def _plan_from_artifacts(self, raw: str, prompt: str) -> dict[str, Any]:
        data = _extract_json(raw)
        files = data.get("files") if isinstance(data, dict) else None
        if not isinstance(files, list) or not files:
            raise ProtocolError("artifact fallback returned no files")

        try:
            data = {**data, **merge_chunk_artifacts([parse_chunk_artifact(json.dumps(data))])}
            files = data["files"]
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ProtocolError(f"invalid chunk artifact: {error}") from error

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
        def request_for_capabilities(capabilities):
            return self._planner_request(
                prompt,
                self._context_for_capabilities(capabilities),
                objective,
                criteria,
                history,
                verifier_instruction,
            )

        request = request_for_capabilities(
            self._capabilities()
        )

        current_renderer = (
            lambda capabilities: json.dumps(
                request_for_capabilities(capabilities),
                ensure_ascii=False,
            )
        )
        last_error: Exception | None = None

        for attempt in range(1, self.protocol_attempts + 1):
            label = (
                f"Step {self._visible_step}: selecting the best next safe action"
                if attempt == 1
                else f"Step {self._visible_step}: repairing planner protocol (attempt {attempt}/{self.protocol_attempts})"
            )
            try:
                with self.progress.waiting("🧠", label):
                    raw = self._backend_for_capabilities(
                        current_renderer,
                        self._system("planner"),
                    )
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
                        def current_renderer(
                            capabilities,
                            *,
                            _instruction=(
                                "You are now the execution planner, not a semantic resolver. "
                                "Ignore every previous semantic-resolver schema. "
                                "Return exactly one compact JSON object with objective, "
                                "success_criteria and action. Do not return resolved_terms, "
                                "confidence, material_change or uncertain_terms."
                            ),
                        ):
                            return json.dumps(
                                {
                                    "planner_reset": True,
                                    "instruction": _instruction,
                                    "required_schema": {
                                        "objective": "non-empty string",
                                        "success_criteria": ["measurable requirement"],
                                        "action": {
                                            "type": "write_file",
                                            "path": "relative/file.py",
                                            "content": "complete file content",
                                        },
                                    },
                                    "execution_request": request_for_capabilities(
                                        capabilities
                                    ),
                                },
                                ensure_ascii=False,
                            )
                    else:
                        self.progress.emit(
                            "↻",
                            "Requesting strict JSON regeneration automatically",
                        )
                        def current_renderer(
                            capabilities,
                            *,
                            _raw_text=raw_text,
                            _error=error,
                            _attempt=attempt + 1,
                        ):
                            return strict_repair_request(
                                request_for_capabilities(
                                    capabilities
                                ),
                                _raw_text,
                                _error,
                                _attempt,
                            )

        exact_single_file = (
            self._explicit_single_file_contract_path(
                prompt
            )
        )

        if exact_single_file is not None:
            raise ProtocolError(
                "strict planner failed for exact single-file "
                f"contract {exact_single_file!r}; generic "
                "artifact fallback is not permitted"
            ) from last_error

        self.progress.emit("↻", "Strict planning failed; requesting a generic implementation bundle")
        def artifact_renderer(capabilities):
            return self._artifact_fallback_request(
                prompt,
                self._context_for_capabilities(
                    capabilities
                ),
                objective,
                criteria,
                history,
                last_error,
            )

        try:
            with self.progress.waiting("🧩", "Generating implementation files from the active LLM"):
                raw = self._backend_for_capabilities(
                    artifact_renderer,
                    self._system("planner"),
                )
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

    def _explicit_single_file_contract_path(
        self,
        prompt: str,
    ) -> str | None:
        """Return the one explicitly authorized workspace file, or None.

        Recognition is intentionally narrow. Merely mentioning a path does
        not authorize fail-closed exact-single-file behavior.
        """
        explicit = re.search(
            r"""(?is)
            \bcreate\s+exactly\s+one\s+file\s*:\s*
            (?P<path>
                (?:[A-Za-z0-9_.-]+/)*
                [A-Za-z0-9_.-]+
                \.(?:py|toml|md|json|yaml|yml|txt|ini|cfg|
                    cpp|cc|cxx|h|hpp|js|ts|html|css)
            )
            """,
            str(prompt or ""),
            re.X,
        )

        if explicit is None:
            return None

        raw = (
            explicit.group("path")
            .strip()
            .replace("\\", "/")
        )

        if not raw:
            return None

        candidate = Path(raw).expanduser()

        if candidate.is_absolute():
            return None

        root = (
            Path(self.workspace)
            .expanduser()
            .resolve()
        )

        resolved = (
            root
            / candidate
        ).resolve()

        try:
            return (
                resolved
                .relative_to(root)
                .as_posix()
            )
        except ValueError:
            return None

    @staticmethod
    def _requested_workspace_files(
        prompt: str,
        objective: str,
        criteria: list[str],
    ) -> list[str]:
        """Extract explicit relative file paths requested by the user."""
        combined = "\n".join(
            [
                str(prompt or ""),
                str(objective or ""),
                *(str(item) for item in criteria),
            ]
        )

        candidates = re.findall(
            r"""(?<![\w./-])(
                (?:[A-Za-z0-9_.-]+/)*
                [A-Za-z0-9_.-]+
                \.(?:py|toml|md|json|yaml|yml|txt|ini|cfg|cpp|cc|cxx|h|hpp|js|ts|html|css)
            )(?![\w./-])""",
            combined,
            re.X,
        )

        files: list[str] = []

        for candidate in candidates:
            normalized = candidate.strip().replace("\\", "/")

            if (
                not normalized
                or normalized.startswith("/")
                or normalized.startswith("../")
                or "/../" in normalized
                or normalized in files
            ):
                continue

            files.append(normalized)

        return files

    def _reconcile_filesystem_verdict(
        self,
        verdict: dict[str, Any],
        prompt: str,
        objective: str,
        criteria: list[str],
    ) -> dict[str, Any]:
        """Override unsupported model claims with actual filesystem evidence."""
        root = Path(self.workspace).expanduser().resolve()

        requested_files = self._requested_workspace_files(
            prompt,
            objective,
            criteria,
        )

        missing_files = [
            relative
            for relative in requested_files
            if not (root / relative).is_file()
        ]

        if not missing_files:
            return verdict

        missing_requirements = [
            f"{relative} is missing from the workspace"
            for relative in missing_files
        ]

        report = getattr(self.executor, "report", None)
        file_evidence = getattr(report, "files", []) if report is not None else []

        successful_writes = [
            item
            for item in file_evidence
            if (
                getattr(item, "operation", "") in {
                    "write",
                    "create",
                    "replace",
                    "patch",
                }
                and bool(getattr(item, "ok", True))
            )
        ]

        if not successful_writes:
            missing_requirements.append(
                "No successful filesystem write evidence exists"
            )

        verdict["goal_met"] = False
        verdict["confidence"] = 0
        verdict["missing_requirements"] = missing_requirements
        verdict["next_instruction"] = (
            "Create the missing files using concrete filesystem actions, "
            "inspect the actual workspace, then run the required tests "
            "or commands."
        )
        verdict["final_answer"] = ""
        verdict["verification_mode"] = "filesystem_reconciliation"

        return verdict

    def _deterministic_exact_single_file_prewrite_failure_verdict(
        self,
        prompt: str,
        observation: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Fail deterministically when exact planning stopped before mutation."""
        requested = (
            self._explicit_single_file_contract_path(
                prompt
            )
        )

        if requested is None:
            return None

        if str(
            observation.get("status") or ""
        ).strip().lower() != "error":
            return None

        error_text = str(
            observation.get("error") or ""
        )

        if (
            "strict planner failed for exact single-file contract"
            not in error_text
        ):
            return None

        if (
            "generic artifact fallback is not permitted"
            not in error_text
        ):
            return None

        report = getattr(
            self.executor,
            "report",
            None,
        )

        files = (
            list(getattr(report, "files", []) or [])
            if report is not None
            else []
        )

        commands = (
            list(getattr(report, "commands", []) or [])
            if report is not None
            else []
        )

        if files or commands:
            return None

        root = (
            Path(self.workspace)
            .expanduser()
            .resolve()
        )

        target = (
            root
            / requested
        ).resolve()

        try:
            target.relative_to(root)
        except ValueError:
            return None

        if target.exists():
            return None

        return {
            "goal_met": False,
            "confidence": 1,
            "missing_requirements": [
                (
                    "The exact requested file was not created "
                    "because strict planning failed before any "
                    "workspace action."
                )
            ],
            "next_instruction": (
                "Retry planning for the same exact "
                "single-file contract."
            ),
            "final_answer": "",
            "verification_mode": (
                "deterministic_exact_single_file_"
                "prewrite_failure"
            ),
            "mechanical_verification": {
                "passed": False,
                "results": [],
            },
        }

    def _single_file_fastpath_is_filesystem_only(
        self,
        prompt: str,
        requested_path: str,
    ) -> bool:
        """Allow full deterministic completion only for a narrow write contract.

        Exact single-file recognition is deliberately broader because it also
        protects planner failure from unsafe generic artifact fallback. Full
        goal completion is narrower: filesystem evidence must be sufficient
        to prove every user-visible requirement.
        """
        requested = str(
            requested_path
            or ""
        ).strip().replace(
            "\\",
            "/",
        )

        if not requested:
            return False

        escaped = re.escape(
            requested
        )

        pattern = rf"""(?isx)
            \A\s*
            create\s+exactly\s+one\s+file\s*:\s*
            {escaped}
            \s*
            (?:
                the\s+first\s+and\s+only\s+
                workspace-changing\s+action\s+
                must\s+be\s*:\s*
                write_file\s+{escaped}
                \s*
            )?
            (?:
                do\s+not\s+modify\s+any\s+other\s+file\.
                \s*
            )?
            success\s+means\s+only\s+that\s+
            {escaped}\s+is\s+created\s+and\s+is\s+nonempty\.
            \s*\Z
        """

        return (
            re.fullmatch(
                pattern,
                str(prompt or ""),
            )
            is not None
        )

    def _deterministic_single_file_write_verdict(
        self,
        prompt: str,
        observation: dict[str, Any],
        *,
        mechanical: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Finish only an explicit, fully evidenced one-file write contract.

        This is intentionally narrower than the generic execution contract.
        Any ambiguity falls through to the normal semantic verifier.
        """
        checks = list(
            self._current_checks
            or []
        )

        if checks:
            if mechanical is None:
                return None

            if not isinstance(
                mechanical,
                dict,
            ):
                return None

            if mechanical.get("passed") is not True:
                return None

            results = mechanical.get(
                "results"
            )

            if not isinstance(
                results,
                list,
            ):
                return None

            if len(results) != len(checks):
                return None

            for check, result in zip(
                checks,
                results,
            ):
                if not isinstance(
                    result,
                    dict,
                ):
                    return None

                if result.get("passed") is not True:
                    return None

                if result.get("check") != check:
                    return None

        elif mechanical is not None:
            return None

        if bool(
            getattr(
                self,
                "_requires_command",
                False,
            )
        ):
            return None

        if str(
            observation.get("status")
            or ""
        ).strip().lower() != "written":
            return None

        observed = observation.get("file")

        if not isinstance(
            observed,
            dict,
        ):
            return None

        observed_path = str(
            observed.get("path")
            or ""
        ).strip().replace("\\", "/")

        if not observed_path:
            return None

        requested_path = (
            self._explicit_single_file_contract_path(
                prompt
            )
        )

        if requested_path is None:
            return None

        root = (
            Path(self.workspace)
            .expanduser()
            .resolve()
        )

        def workspace_relative(
            value: object,
        ) -> str | None:
            raw = str(
                value
                or ""
            ).strip()

            if not raw:
                return None

            candidate = (
                Path(raw)
                .expanduser()
            )

            if not candidate.is_absolute():
                candidate = (
                    root
                    / candidate
                )

            resolved = candidate.resolve()

            try:
                return (
                    resolved
                    .relative_to(root)
                    .as_posix()
                )
            except ValueError:
                return None

        requested_relative = (
            workspace_relative(
                requested_path
            )
        )

        observed_relative = (
            workspace_relative(
                observed_path
            )
        )

        if (
            requested_relative is None
            or observed_relative is None
            or requested_relative
            != observed_relative
        ):
            return None

        if checks:
            for check in checks:
                if not isinstance(
                    check,
                    dict,
                ):
                    return None

                kind = str(
                    check.get("type")
                    or ""
                ).strip()

                if kind not in {
                    "file_exists",
                    "contains",
                }:
                    return None

                check_path = str(
                    check.get("path")
                    or ""
                ).strip().replace(
                    "\\",
                    "/",
                )

                check_relative = (
                    workspace_relative(
                        check_path
                    )
                )

                if (
                    check_relative is None
                    or check_relative
                    != requested_relative
                ):
                    return None

                if (
                    kind == "contains"
                    and not str(
                        check.get("text")
                        or ""
                    )
                ):
                    return None

        report = getattr(
            self.executor,
            "report",
            None,
        )

        file_evidence = (
            list(
                getattr(
                    report,
                    "files",
                    [],
                )
                or []
            )
            if report is not None
            else []
        )

        if len(file_evidence) != 1:
            return None

        evidence = file_evidence[0]

        evidence_path = str(
            getattr(
                evidence,
                "path",
                "",
            )
            or ""
        ).strip().replace("\\", "/")

        evidence_relative = (
            workspace_relative(
                evidence_path
            )
        )

        if (
            evidence_relative is None
            or evidence_relative
            != requested_relative
        ):
            return None

        target = (
            root
            / requested_relative
        ).resolve()

        try:
            target.relative_to(root)
        except ValueError:
            return None

        if not target.is_file():
            return None

        data = target.read_bytes()

        if not data:
            return None

        evidence_size = getattr(
            evidence,
            "size",
            None,
        )

        observed_size = observed.get(
            "size"
        )

        if (
            evidence_size is None
            or observed_size is None
            or int(evidence_size) != len(data)
            or int(observed_size) != len(data)
        ):
            return None

        from hashlib import sha256

        digest = sha256(data).hexdigest()

        evidence_sha = str(
            getattr(
                evidence,
                "sha256",
                "",
            )
            or ""
        )

        observed_sha = str(
            observed.get("sha256")
            or ""
        )

        if (
            not evidence_sha
            or not observed_sha
            or evidence_sha != digest
            or observed_sha != digest
        ):
            return None

        mechanical_result = (
            mechanical
            if mechanical is not None
            else {
                "passed": None,
                "results": [],
            }
        )

        if not self._single_file_fastpath_is_filesystem_only(
            prompt,
            requested_relative,
        ):
            return {
                "goal_met": False,
                "confidence": 1,
                "missing_requirements": [
                    (
                        "The requested file write is verified, "
                        "but substantive content requirements "
                        "are not proven by filesystem evidence."
                    )
                ],
                "next_instruction": (
                    "Audit the written file against the "
                    "remaining content requirements."
                ),
                "final_answer": "",
                "verification_mode": (
                    "deterministic_single_file_"
                    "content_unverified"
                ),
                "mechanical_verification": (
                    mechanical_result
                ),
            }

        return {
            "goal_met": True,
            "confidence": 1,
            "missing_requirements": [],
            "next_instruction": "",
            "final_answer": (
                "Objective completed with verified "
                "single-file filesystem evidence."
            ),
            "verification_mode": (
                "deterministic_single_file_write"
            ),
            "mechanical_verification": (
                mechanical_result
            ),
        }

    def _verify(
        self,
        prompt: str,
        objective: str,
        criteria: list[str],
        history: list[StepRecord],
        observation: dict[str, Any],
    ) -> dict[str, Any]:
        observation = dict(observation)

        deterministic_failure = (
            self._deterministic_exact_single_file_prewrite_failure_verdict(
                prompt,
                observation,
            )
        )

        if deterministic_failure is not None:
            return deterministic_failure

        deterministic_verdict = (
            self._deterministic_single_file_write_verdict(
                prompt,
                observation,
            )
        )

        if deterministic_verdict is not None:
            return deterministic_verdict

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

        if self._current_checks:
            deterministic_verdict = (
                self._deterministic_single_file_write_verdict(
                    prompt,
                    observation,
                    mechanical=mechanical,
                )
            )

            if deterministic_verdict is not None:
                return deterministic_verdict

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

        verdict = self._reconcile_filesystem_verdict(
            verdict,
            prompt,
            objective,
            criteria,
        )

        return verdict
