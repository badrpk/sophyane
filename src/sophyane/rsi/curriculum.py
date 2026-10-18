"""Durable, bounded state for continuous RSI curriculum scheduling."""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class _TextEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class TaskSource(_TextEnum):
    WEAKNESS = "weakness"
    REGRESSION = "regression"
    CAPABILITY_GAP = "capability_gap"
    CURRICULUM = "curriculum"
    LLM_FOLLOW_UP = "llm_follow_up"


class TaskStatus(_TextEnum):
    QUEUED = "queued"
    RUNNING = "running"
    VERIFIED = "verified"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"
    PAUSED = "paused"


class ResourceClass(_TextEnum):
    LIGHT = "light"
    NORMAL = "normal"
    PAUSED = "paused"


@dataclass
class CurriculumTask:
    task_id: str
    parent_ability_id: str
    objective: str
    editable_paths: tuple[str, ...]
    verification: tuple[str, ...]
    source: TaskSource
    resource_class: ResourceClass = ResourceClass.NORMAL
    status: TaskStatus = TaskStatus.QUEUED
    failure_reason: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None


@dataclass(frozen=True)
class AbilityRecord:
    ability_id: str
    name: str
    evidence: tuple[str, ...]
    task_id: str = ""
    promoted_checkpoint: str = ""
    recorded_at: float = field(default_factory=time.time)


@dataclass
class CurriculumState:
    schema_version: int = 1
    queue: list[CurriculumTask] = field(default_factory=list)
    abilities: list[AbilityRecord] = field(default_factory=list)
    current_task_id: str | None = None
    iteration: int = 0
    started_at: float | None = None
    paused: bool = False
    stopped: bool = False
    stop_reason: str = ""
    last_result: dict[str, Any] = field(default_factory=dict)


def _enum_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_enum_value(item) for item in value]
    if isinstance(value, list):
        return [_enum_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _enum_value(item) for key, item in value.items()}
    return value


def _task_from_dict(raw: dict[str, Any]) -> CurriculumTask:
    return CurriculumTask(
        task_id=str(raw["task_id"]),
        parent_ability_id=str(raw.get("parent_ability_id", "")),
        objective=str(raw["objective"]),
        editable_paths=tuple(str(item) for item in raw.get("editable_paths", [])),
        verification=tuple(str(item) for item in raw.get("verification", [])),
        source=TaskSource(str(raw["source"])),
        resource_class=ResourceClass(str(raw.get("resource_class", ResourceClass.NORMAL.value))),
        status=TaskStatus(str(raw.get("status", TaskStatus.QUEUED.value))),
        failure_reason=str(raw.get("failure_reason", "")),
        created_at=float(raw.get("created_at", time.time())),
        started_at=raw.get("started_at"),
        completed_at=raw.get("completed_at"),
    )


def _ability_from_dict(raw: dict[str, Any]) -> AbilityRecord:
    return AbilityRecord(
        ability_id=str(raw["ability_id"]),
        name=str(raw["name"]),
        evidence=tuple(str(item) for item in raw.get("evidence", [])),
        task_id=str(raw.get("task_id", "")),
        promoted_checkpoint=str(raw.get("promoted_checkpoint", "")),
        recorded_at=float(raw.get("recorded_at", time.time())),
    )


class CurriculumStore:
    """Atomic JSON state plus append-only audit events."""

    def __init__(self, path: Path):
        self.path = Path(path).expanduser()
        if self.path.name in {"", ".", ".."}:
            raise ValueError("invalid curriculum state path")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.events_path = self.path.with_name(self.path.stem + ".events.jsonl")

    def load(self) -> CurriculumState:
        if not self.path.exists():
            return CurriculumState()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or int(raw.get("schema_version", 0)) != 1:
                raise ValueError("unsupported schema")
            state = CurriculumState(
                schema_version=1,
                queue=[_task_from_dict(item) for item in raw.get("queue", [])],
                abilities=[_ability_from_dict(item) for item in raw.get("abilities", [])],
                current_task_id=raw.get("current_task_id"),
                iteration=int(raw.get("iteration", 0)),
                started_at=raw.get("started_at"),
                paused=bool(raw.get("paused", False)),
                stopped=bool(raw.get("stopped", False)),
                stop_reason=str(raw.get("stop_reason", "")),
                last_result=dict(raw.get("last_result", {})),
            )
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid curriculum state: {error}") from error

        for task in state.queue:
            if task.status is TaskStatus.RUNNING:
                task.status = TaskStatus.PAUSED
                task.failure_reason = "paused after process restart"
        if state.current_task_id and not any(
            task.task_id == state.current_task_id and task.status is TaskStatus.RUNNING
            for task in state.queue
        ):
            state.current_task_id = None
        return state

    def save(self, state: CurriculumState) -> None:
        payload = _enum_value(asdict(state))
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def append_event(self, event: dict[str, object]) -> None:
        record = {"recorded_at": time.time(), **_enum_value(event)}
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
