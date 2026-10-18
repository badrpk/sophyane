"""Strict, non-mutating validation for LLM-generated RSI follow-up tasks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Callable, Any

from .curriculum import AbilityRecord, CurriculumTask, TaskSource


@dataclass(frozen=True)
class ProposalContext:
    ability: AbilityRecord
    allowed_paths: tuple[str, ...]
    existing_task_ids: tuple[str, ...]
    capability_summary: str


@dataclass(frozen=True)
class ProposalResult:
    accepted: bool
    task: CurriculumTask | None = None
    reason: str = ""


class CurriculumProposalAdapter:
    def __init__(self, generate: Callable[[str], str], authority: Callable[[str], bool] | None = None):
        self.generate = generate
        self.authority = authority or (lambda path: path.startswith("src/sophyane/"))

    def _reject(self, reason: str) -> ProposalResult:
        return ProposalResult(False, None, reason)

    def propose(self, context: ProposalContext) -> ProposalResult:
        prompt = json.dumps(
            {
                "ability": context.ability.name,
                "capability_summary": context.capability_summary,
                "allowed_paths": list(context.allowed_paths),
                "existing_task_ids": list(context.existing_task_ids),
                "required_output": "one JSON task object only",
            },
            sort_keys=True,
        )
        try:
            raw = self.generate(prompt)
            payload: Any = json.loads(raw)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            return self._reject(f"invalid JSON proposal: {error}")

        if not isinstance(payload, dict) or "tasks" in payload:
            return self._reject("proposal must contain exactly one task object")
        required = {"task_id", "parent_ability_id", "objective", "editable_paths", "verification"}
        if not required.issubset(payload):
            missing = sorted(required - set(payload))
            return self._reject(f"missing required fields: {', '.join(missing)}")

        task_id = str(payload["task_id"]).strip()
        parent_id = str(payload["parent_ability_id"]).strip()
        objective = str(payload["objective"]).strip()
        paths = payload["editable_paths"]
        verification = payload["verification"]
        if not task_id or task_id in context.existing_task_ids:
            return self._reject("duplicate or empty task_id")
        if parent_id != context.ability.ability_id:
            return self._reject("parent ability does not match current ability")
        if not objective or len(objective) > 1000:
            return self._reject("objective must be between 1 and 1000 characters")
        if any(
            marker in objective.lower()
            for marker in (
                "delete repository",
                "delete the repository",
                "disable safety",
                "disable all safety",
                "rm -rf",
                "destroy",
            )
        ):
            return self._reject("destructive objective is not allowed")
        if not isinstance(paths, list) or not paths or len(paths) > 8:
            return self._reject("editable_paths must contain 1 to 8 paths")
        if not isinstance(verification, list) or not verification or len(verification) > 16:
            return self._reject("verification must contain 1 to 16 arguments")

        normalized: list[str] = []
        allowed = set(context.allowed_paths)
        for raw_path in paths:
            path = str(raw_path).replace("\\", "/").strip()
            pure = PurePosixPath(path)
            if not path or pure.is_absolute() or ".." in pure.parts or path not in allowed or not self.authority(path):
                return self._reject(f"unsafe or unauthorized path: {path!r}")
            normalized.append(path)

        if any(not str(item).strip() for item in verification):
            return self._reject("verification contains an empty argument")
        task = CurriculumTask(
            task_id=task_id,
            parent_ability_id=parent_id,
            objective=objective,
            editable_paths=tuple(normalized),
            verification=tuple(str(item) for item in verification),
            source=TaskSource.LLM_FOLLOW_UP,
            component=str(payload.get("component", "")).strip(),
        )
        return ProposalResult(True, task, "accepted")
