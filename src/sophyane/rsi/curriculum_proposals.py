"""Strict, non-mutating validation for LLM-generated RSI follow-up tasks."""

from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Any

from .curriculum import AbilityRecord, CurriculumTask, TaskSource
from .repository_inventory import RepositoryRecord


@dataclass(frozen=True)
class ProposalContext:
    ability: AbilityRecord
    allowed_paths: tuple[str, ...]
    existing_task_ids: tuple[str, ...]
    capability_summary: str
    repository: RepositoryRecord | None = None
    repository_id: str = ""
    base_commit: str = ""


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

    def _prompt(self, context: ProposalContext) -> str:
        return json.dumps(
            {
                "ability": context.ability.name,
                "capability_summary": context.capability_summary,
                "allowed_paths": list(context.allowed_paths),
                "existing_task_ids": list(context.existing_task_ids),
                "repository_id": context.repository_id,
                "base_commit": context.base_commit,
                "required_fields": ["repository_id", "base_commit", "red_command", "red_failure_marker", "green_commands"],
                "required_output": "one JSON task object only",
            },
            sort_keys=True,
        )

    def propose(self, context: ProposalContext) -> ProposalResult:
        try:
            raw = self.generate(self._prompt(context))
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            return self._reject(f"invalid JSON proposal: {error}")
        return self.validate(raw, context)

    def validate(self, raw: str, context: ProposalContext) -> ProposalResult:
        try:
            payload: Any = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            return self._reject(f"invalid JSON proposal: {error}")

        if not isinstance(payload, dict) or "tasks" in payload:
            return self._reject("proposal must contain exactly one task object")
        bound = context.repository is not None or bool(context.repository_id or context.base_commit)
        required = {"task_id", "parent_ability_id", "objective", "editable_paths", "verification"}
        if bound:
            required.update({"repository_id", "base_commit", "red_command", "red_failure_marker", "green_commands"})
        if not required.issubset(payload):
            missing = sorted(required - set(payload))
            return self._reject(f"missing required fields: {', '.join(missing)}")

        task_id = str(payload["task_id"]).strip()
        parent_id = str(payload["parent_ability_id"]).strip()
        objective = str(payload["objective"]).strip()
        paths = payload["editable_paths"]
        verification = payload["verification"]
        repository_id = str(payload.get("repository_id", "")).strip()
        base_commit = str(payload.get("base_commit", "")).strip()
        red_command = payload.get("red_command", [])
        red_failure_marker = payload.get("red_failure_marker", "")
        green_commands = payload.get("green_commands", [])
        if bound:
            repository = context.repository
            if repository is None or not context.repository_id or context.repository_id != repository.repo_id:
                return self._reject("selected repository identity is invalid")
            if not re.fullmatch(r"[0-9a-fA-F]{40}", context.base_commit) or context.base_commit != repository.commit:
                return self._reject("selected repository base commit is stale or invalid")
            if repository_id != context.repository_id or base_commit != context.base_commit:
                return self._reject("proposal repository identity or base commit does not match")
            if not isinstance(red_command, list) or not red_command or any(not isinstance(item, str) or not item.strip() for item in red_command):
                return self._reject("red_command must be one nonempty command")
            if not isinstance(red_failure_marker, str) or not red_failure_marker.strip():
                return self._reject("red_failure_marker is required")
            if not isinstance(green_commands, list) or not green_commands or any(
                not isinstance(command, list) or not command or any(not isinstance(item, str) or not item.strip() for item in command)
                for command in green_commands
            ):
                return self._reject("green_commands must contain nonempty commands")
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
            path = str(raw_path).strip()
            pure = PurePosixPath(path)
            if not path or "\\" in path or pure.is_absolute() or any(part in {"", ".", ".."} for part in path.split("/")) or path not in allowed:
                return self._reject(f"unsafe or unauthorized path: {path!r}")
            if bound:
                root = Path(context.repository.path).resolve()
                target = (root / path).resolve()
                permitted = any(
                    pure == PurePosixPath(policy) or PurePosixPath(policy) in pure.parents
                    for policy in context.repository.editable_paths
                )
                if not target.is_relative_to(root) or not permitted:
                    return self._reject(f"unsafe or unauthorized path: {path!r}")
            elif not self.authority(path):
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
            repository_id=repository_id,
            base_commit=base_commit,
            proposal_digest=hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest() if bound else "",
            red_command=tuple(red_command) if bound else (),
            red_failure_marker=red_failure_marker.strip() if bound else "",
            green_commands=tuple(tuple(command) for command in green_commands) if bound else (),
        )
        return ProposalResult(True, task, "accepted")
