"""Sophyane v16 repository-aware coding agent."""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Callable

from sophyane.coding_runtime import (
    DependencyAdvisor,
    GitCheckpoint,
    MechanicalVerifier,
    PatchEngine,
    RepositoryIndex,
    TaskQueue,
)
from sophyane.context_builder import ContextBuilder, ContextPacket
from sophyane.providers.base import ProviderCapabilities
from sophyane.doer import DoerRuntime, StepRecord, _extract_json


class CodingDoerRuntime(DoerRuntime):
    """Extend the v15 doer with repository intelligence and batched tools."""

    MAX_BATCH_ACTIONS = 12

    def __init__(
        self,
        *args: Any,
        capabilities: ProviderCapabilities
        | Callable[[], ProviderCapabilities]
        | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.capabilities = capabilities
        self.index = RepositoryIndex(self.workspace)
        self.patch_engine = PatchEngine(self.workspace)
        self.mechanical = MechanicalVerifier(self.workspace)
        self.git = GitCheckpoint(self.workspace)
        self.repository_snapshot = self.index.build()
        self.checkpoints: list[dict[str, Any]] = []
        self.task_queue = TaskQueue()
        self._coding_context_packet = ContextPacket()

    # SOPHYANE_CODING_PROVIDER_AWARE_REPOSITORY_CONTEXT_V1
    def _capabilities(self) -> ProviderCapabilities:
        value = self.capabilities
        if callable(value):
            try:
                value = value()
            except Exception:
                return ProviderCapabilities()
        if isinstance(value, ProviderCapabilities):
            return value
        return ProviderCapabilities()

    def _read_repository_context_file(self, relative: str) -> str | None:
        path = (self.workspace / relative).resolve()
        if path != self.workspace and self.workspace not in path.parents:
            return None
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    @staticmethod
    def _system(role: str) -> str:
        normalized_role = role.strip().lower()
        role_marker = f"SOPHYANE_ROLE={normalized_role.upper()}. "
        base = (
            role_marker
            + "You are part of Sophyane v16, a repository-aware autonomous coding agent. "
            "Return exactly one JSON object. Use repository context, symbols, tests and manifests. "
            "Prefer precise patches over whole-file rewrites for existing files. "
            "Batch independent safe actions when this reduces model calls. "
            "Workspace writes, safe commands, tests and local Git inspection are pre-authorized. "
            "Never invent permission rituals. Repair failures from diagnostics automatically."
        )
        if normalized_role == "planner":
            return base + (
                " Allowed actions: answer, write_file, apply_patch, replace_lines, run_command, "
                "read_file, search_repository, git_checkpoint, verify_checks, create_task_queue, "
                "batch, ask_user. A batch contains actions:[...], executed in order, maximum 12. "
                "For existing files use apply_patch with path, old, new, expected_count. "
                "For repository-scale work create a dependency task queue, then execute ready tasks. "
                "Provide deterministic_checks when completion can be mechanically verified. "
                "Schema: {objective, success_criteria, deterministic_checks:[...], action:{...}, rationale}."
            )
        if normalized_role == "verifier":
            return base + (
                " Accept deterministic check failures as authoritative. Do not mark completion when "
                "required tests, files or expected output are unverified. Return "
                "{goal_met, confidence, missing_requirements, next_instruction, final_answer}."
            )
        return base

    def _context(self, prompt: str) -> str:
        base = super()._context(prompt)
        self.repository_snapshot = self.index.build()

        search_hits = self.index.search(prompt, limit=10)
        ranked_paths = self.index.ranked_context_paths(
            prompt,
            limit=12,
        )

        direct_paths: set[str] = set()
        for item in self.index.search(prompt, limit=36):
            relative = str(item.get("path", ""))
            if relative:
                direct_paths.add(relative)

        summary = {
            "file_count": len(self.repository_snapshot.files),
            "symbol_count": len(self.repository_snapshot.symbols),
            "tests": self.repository_snapshot.tests[:100],
            "manifests": self.repository_snapshot.manifests,
            "digest": self.repository_snapshot.digest,
        }

        packet = ContextPacket()

        # Compact repository intelligence outranks large source files for
        # bounded providers. This prevents one oversized high-ranked file from
        # evicting every useful repository clue before it is itself omitted.
        packet.add(
            "Repository summary",
            json.dumps(summary, ensure_ascii=False),
            priority=100,
        )

        if search_hits:
            packet.add(
                "Repository search hits",
                json.dumps(search_hits, ensure_ascii=False),
                priority=95,
            )

        for position, relative in enumerate(ranked_paths):
            text = self._read_repository_context_file(relative)
            if text is None:
                continue

            direct = relative in direct_paths
            packet.add(
                (
                    f"Direct repository file: {relative}"
                    if direct
                    else f"Repository dependency: {relative}"
                ),
                text,
                priority=(
                    max(75, 85 - position)
                    if direct
                    else max(50, 60 - position)
                ),
            )

        if base:
            packet.add(
                "Persistent coding context",
                base,
                priority=70,
            )

        # Preserve the unreduced packet so heterogeneous fallback children can
        # each perform truthful provider-specific admission.
        self._coding_context_packet = packet

        return self._context_for_capabilities(
            self._capabilities()
        )

    # SOPHYANE_CODING_PER_CHILD_CONTEXT_RENDERING_V1
    def _context_for_capabilities(
        self,
        capabilities: ProviderCapabilities,
    ) -> str:
        if not isinstance(
            capabilities,
            ProviderCapabilities,
        ):
            capabilities = ProviderCapabilities()

        return ContextBuilder(
            capabilities
        ).build(
            self._coding_context_packet
        ).text

    # SOPHYANE_CODING_CAPABILITY_BACKEND_V1
    def _backend_for_capabilities(
        self,
        renderer: Callable[[ProviderCapabilities], str],
        system: str,
    ) -> str:
        hook = getattr(
            self.backend,
            "generate_for_capabilities",
            None,
        )

        if callable(hook):
            return hook(
                renderer,
                system,
            )

        return self.backend(
            renderer(self._capabilities()),
            system,
        )

    # SOPHYANE_PROVIDER_AWARE_VERIFIER_EVIDENCE_V1
    def _verifier_payload_for_capabilities(
        self,
        *,
        prompt: str,
        objective: str,
        criteria: list[str],
        history: list[StepRecord],
        observation: dict[str, Any],
        mechanical: dict[str, Any],
        repository_digest: str,
        git_status: Any,
        capabilities: ProviderCapabilities,
    ) -> dict[str, Any]:
        values: dict[str, Any] = {
            "user_request": prompt,
            "objective": objective,
            "success_criteria": criteria,
            "prior_steps": [
                asdict(item)
                for item in history[-4:]
            ],
            "latest_observation": observation,
            "execution_report": self.executor.report.to_dict(),
            "repository_digest": repository_digest,
            "mechanical_verification": mechanical,
            "git_status": git_status,
            "instruction": (
                "Mark goal_met true only when all requirements are evidenced. "
                "Mechanical failures are authoritative. For coding work require "
                "successful relevant tests or commands unless the user explicitly "
                "requested code only."
            ),
        }

        packet = ContextPacket()

        def add(
            key: str,
            *,
            priority: int,
            pinned: bool = False,
        ) -> None:
            packet.add(
                key,
                json.dumps(
                    values[key],
                    ensure_ascii=False,
                    default=str,
                ),
                priority=priority,
                pinned=pinned,
            )

        # Immutable verification contract survives bounded admission.
        add(
            "user_request",
            priority=100,
            pinned=True,
        )
        add(
            "objective",
            priority=100,
            pinned=True,
        )
        add(
            "success_criteria",
            priority=100,
            pinned=True,
        )
        add(
            "mechanical_verification",
            priority=100,
            pinned=True,
        )
        add(
            "instruction",
            priority=100,
            pinned=True,
        )

        # Current evidence is more useful than historical evidence.
        add(
            "latest_observation",
            priority=90,
        )
        add(
            "execution_report",
            priority=85,
        )
        add(
            "repository_digest",
            priority=70,
        )
        add(
            "git_status",
            priority=60,
        )
        add(
            "prior_steps",
            priority=50,
        )

        if not isinstance(
            capabilities,
            ProviderCapabilities,
        ):
            capabilities = ProviderCapabilities()

        admitted = ContextBuilder(
            capabilities
        ).build(packet)

        included = {
            item.label
            for item in admitted.included
        }

        return {
            key: value
            for key, value in values.items()
            if key in included
        }

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
                "Choose the highest-leverage safe next action or batch. "
                "Do not claim browser or deployment capabilities that are unavailable. "
                "Prefer targeted reads and patches, then run focused tests."
            ),
        }
        return _extract_json(
            self.backend(
                json.dumps(request, ensure_ascii=False),
                self._system("planner"),
            )
        )

    def _read_file(self, action: dict[str, Any]) -> dict[str, Any]:
        relative = str(action.get("path", ""))
        path = (self.workspace / relative).resolve()
        if path != self.workspace and self.workspace not in path.parents:
            raise PermissionError("read path escapes workspace")
        start = max(1, int(action.get("start_line", 1)))
        end = int(action.get("end_line", start + 399))
        lines = path.read_text(encoding="utf-8").splitlines()
        excerpt = "\n".join(lines[start - 1 : end])
        return {
            "status": "read",
            "path": str(path),
            "start_line": start,
            "end_line": min(end, len(lines)),
            "content": excerpt,
        }

    def _execute_one(self, action: dict[str, Any]) -> dict[str, Any]:
        kind = str(action.get("type", "")).strip().lower()
        if kind == "read_file":
            return self._read_file(action)
        if kind == "search_repository":
            query = str(action.get("query", ""))
            return {
                "status": "searched",
                "query": query,
                "results": self.index.search(
                    query,
                    limit=int(action.get("limit", 30)),
                ),
                "context": self.index.context(
                    query,
                    max_chars=int(action.get("max_chars", 16_000)),
                ),
            }
        if kind == "apply_patch":
            evidence = self.patch_engine.replace_exact(
                str(action.get("path", "")),
                str(action.get("old", "")),
                str(action.get("new", "")),
                expected_count=int(action.get("expected_count", 1)),
            )
            self.executor.verify_file(str(action.get("path", "")))
            self.index.build()
            return {"status": "patched", "evidence": evidence}
        if kind == "replace_lines":
            evidence = self.patch_engine.replace_lines(
                str(action.get("path", "")),
                int(action.get("start_line", 0)),
                int(action.get("end_line", 0)),
                str(action.get("content", "")),
            )
            self.executor.verify_file(str(action.get("path", "")))
            self.index.build()
            return {"status": "patched", "evidence": evidence}
        if kind == "git_checkpoint":
            checkpoint = self.git.checkpoint(
                str(action.get("label", "sophyane-v16"))
            )
            self.checkpoints.append(checkpoint)
            return {"status": "checkpointed", "checkpoint": checkpoint}
        if kind == "verify_checks":
            checks = action.get("checks", [])
            if not isinstance(checks, list):
                raise ValueError("verify_checks requires checks list")
            result = self.mechanical.verify(
                checks,
                command_observations=[
                    asdict(item) for item in self.executor.report.commands
                ],
            )
            return {"status": "mechanically_verified", "result": result}
        if kind == "create_task_queue":
            tasks = action.get("tasks", [])
            if not isinstance(tasks, list):
                raise ValueError("create_task_queue requires tasks list")
            self.task_queue = TaskQueue(tasks)
            return {"status": "queue_created", **self.task_queue.to_dict()}
        observation = super()._execute(action)
        if observation.get("status") == "command_failed":
            stderr = str(observation.get("command", {}).get("stderr", ""))
            dependency = DependencyAdvisor.diagnose(stderr)
            if dependency:
                observation["dependency_diagnosis"] = dependency
        if kind == "write_file":
            self.index.build()
        return observation

    def _execute(self, action: dict[str, Any]) -> dict[str, Any]:
        if str(action.get("type", "")).strip().lower() != "batch":
            return self._execute_one(action)
        actions = action.get("actions")
        if not isinstance(actions, list) or not actions:
            raise ValueError("batch requires non-empty actions list")
        if len(actions) > self.MAX_BATCH_ACTIONS:
            raise ValueError(
                f"batch exceeds maximum of {self.MAX_BATCH_ACTIONS} actions"
            )
        observations: list[dict[str, Any]] = []
        for position, child in enumerate(actions, start=1):
            if not isinstance(child, dict):
                raise ValueError("every batch action must be an object")
            observation = self._execute_one(child)
            observations.append(
                {
                    "position": position,
                    "action": child,
                    "observation": observation,
                }
            )
            if observation.get("status") in {
                "command_failed",
                "error",
                "needs_user",
            }:
                break
        failed = next(
            (
                item
                for item in observations
                if item["observation"].get("status")
                in {"command_failed", "error", "needs_user"}
            ),
            None,
        )
        return {
            "status": "batch_failed" if failed else "batch_executed",
            "actions_completed": len(observations),
            "observations": observations,
            "repair_required": bool(failed),
        }

    def _verify(
        self,
        prompt: str,
        objective: str,
        criteria: list[str],
        history: list[StepRecord],
        observation: dict[str, Any],
    ) -> dict[str, Any]:
        plan_checks: list[dict[str, Any]] = []
        if history:
            prior_action = history[-1].action
            raw = (
                prior_action.get("deterministic_checks", [])
                if isinstance(prior_action, dict)
                else []
            )
            if isinstance(raw, list):
                plan_checks = raw
        latest_action = observation.get("deterministic_checks", [])
        if isinstance(latest_action, list):
            plan_checks.extend(latest_action)
        mechanical = (
            self.mechanical.verify(
                plan_checks,
                command_observations=[
                    asdict(item) for item in self.executor.report.commands
                ],
            )
            if plan_checks
            else {"passed": None, "results": []}
        )
        repository_digest = self.index.build().digest
        git_status = self.git.status()

        def verifier_renderer(
            capabilities: ProviderCapabilities,
        ) -> str:
            payload = self._verifier_payload_for_capabilities(
                prompt=prompt,
                objective=objective,
                criteria=criteria,
                history=history,
                observation=observation,
                mechanical=mechanical,
                repository_digest=repository_digest,
                git_status=git_status,
                capabilities=capabilities,
            )

            return json.dumps(
                payload,
                ensure_ascii=False,
            )

        verdict = _extract_json(
            self._backend_for_capabilities(
                verifier_renderer,
                self._system("verifier"),
            )
        )
        if mechanical.get("passed") is False:
            verdict["goal_met"] = False
            failed = [
                item for item in mechanical["results"] if not item["passed"]
            ]
            verdict["missing_requirements"] = [
                f"Mechanical check failed: {item['detail']}" for item in failed
            ]
            verdict["next_instruction"] = (
                "Satisfy the failed deterministic checks, then rerun verification."
            )
        verdict.setdefault("goal_met", False)
        verdict.setdefault("missing_requirements", [])
        verdict.setdefault("next_instruction", "Continue toward unmet requirements")
        verdict.setdefault("final_answer", "")
        return verdict

    def run(self, prompt: str):
        result = super().run(prompt)
        self.repository_snapshot = self.index.build()
        result.execution["repository"] = self.repository_snapshot.to_dict()
        result.execution["git_checkpoints"] = self.checkpoints
        result.execution["task_queue"] = self.task_queue.to_dict()
        return result
