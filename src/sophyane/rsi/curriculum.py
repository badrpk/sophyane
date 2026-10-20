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
    component: str = ""
    attempts: int = 0
    proposal_files: dict[str, str] = field(default_factory=dict)


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
    follow_ups_enqueued: int = 0
    last_verified_at: float | None = None


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
        component=str(raw.get("component", "")),
        attempts=int(raw.get("attempts", 0)),
        proposal_files={str(path): str(content) for path, content in dict(raw.get("proposal_files", {})).items()},
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
                follow_ups_enqueued=int(raw.get("follow_ups_enqueued", 0)),
                last_verified_at=raw.get("last_verified_at"),
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


@dataclass(frozen=True)
class CurriculumPolicy:
    max_iterations: int = 100
    max_wall_seconds: float = 86_400.0
    cooldown_seconds: float = 30.0
    max_queue_length: int = 32
    max_follow_ups: int = 1
    max_task_attempts: int = 3


class CurriculumScheduler:
    """Deterministic, durable lifecycle for one bounded task at a time."""

    _SOURCE_PRIORITY = {
        TaskSource.REGRESSION: 0,
        TaskSource.WEAKNESS: 1,
        TaskSource.CAPABILITY_GAP: 2,
        TaskSource.CURRICULUM: 3,
        TaskSource.LLM_FOLLOW_UP: 4,
    }

    def __init__(self, store: CurriculumStore, policy: CurriculumPolicy, clock=time.time):
        self.store = store
        self.policy = policy
        self.clock = clock

    def _state(self) -> CurriculumState:
        return self.store.load()

    def _save(self, state: CurriculumState, event: dict[str, object] | None = None) -> None:
        self.store.save(state)
        if event:
            self.store.append_event(event)

    def choose_next(self, candidates: list[CurriculumTask]) -> CurriculumTask | None:
        queued = [
            task for task in candidates
            if task.status is TaskStatus.QUEUED
            or (
                task.status is TaskStatus.PAUSED
                and task.failure_reason == "paused after process restart"
            )
        ]
        if not queued:
            return None
        return min(queued, key=lambda item: (self._SOURCE_PRIORITY[item.source], item.created_at, item.task_id))

    def enqueue(self, task: CurriculumTask) -> bool:
        state = self._state()
        active_tasks = sum(
            item.status in {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.PAUSED}
            for item in state.queue
        )
        if active_tasks >= self.policy.max_queue_length:
            reason = "queue full"
        elif any(item.task_id == task.task_id for item in state.queue):
            reason = "duplicate task_id"
        elif not task.objective.strip() or not task.editable_paths or not task.verification:
            reason = "invalid task"
        else:
            reason = ""
        if reason:
            self.store.append_event({"event": "enqueue_rejected", "task_id": task.task_id, "reason": reason})
            return False
        state.queue.append(task)
        self._save(state, {"event": "task_queued", "task_id": task.task_id})
        return True

    def _budget_exhausted(self, state: CurriculumState) -> bool:
        if state.iteration >= self.policy.max_iterations:
            return True
        if state.started_at is not None and self.clock() - state.started_at >= self.policy.max_wall_seconds:
            return True
        return False

    def next_task(self) -> CurriculumTask | None:
        state = self._state()
        if state.stopped or state.paused or state.current_task_id or self._budget_exhausted(state):
            if self._budget_exhausted(state) and not state.paused:
                state.paused = True
                self._save(state, {"event": "budget_paused"})
            return None
        if state.last_verified_at is not None and self.clock() - state.last_verified_at < self.policy.cooldown_seconds:
            return None
        selected = self.choose_next(state.queue)
        if selected is None:
            return None
        state.current_task_id = selected.task_id
        selected.status = TaskStatus.RUNNING
        selected.started_at = self.clock()
        selected.attempts += 1
        self._save(state, {"event": "task_started", "task_id": selected.task_id})
        return selected

    def mark_running(self, task_id: str) -> None:
        state = self._state()
        task = next(item for item in state.queue if item.task_id == task_id)
        task.status = TaskStatus.RUNNING
        task.started_at = task.started_at or self.clock()
        state.current_task_id = task_id
        state.started_at = state.started_at or self.clock()
        self._save(state, {"event": "task_running", "task_id": task_id})

    def record_verified(self, task_id: str, evidence: tuple[str, ...]) -> None:
        state = self._state()
        task = next(item for item in state.queue if item.task_id == task_id)
        task.status = TaskStatus.VERIFIED
        task.completed_at = self.clock()
        state.current_task_id = None
        state.iteration += 1
        state.last_verified_at = self.clock()
        state.last_result = {"task_id": task_id, "status": TaskStatus.VERIFIED.value, "evidence": list(evidence)}
        self._save(state, {"event": "task_verified", "task_id": task_id, "evidence": list(evidence)})

    def reconcile_verified(self, task_id: str, evidence: tuple[str, ...]) -> bool:
        """Close a task whose promotion completed before a daemon restart.

        Restart recovery changes an interrupted RUNNING task to PAUSED.  A
        promotion can finish just before that recovery state is persisted, so
        the task must be allowed to become VERIFIED without being executed a
        second time.  This method is deliberately restricted to non-terminal
        tasks and emits the same durable completion event as normal success.
        """
        state = self._state()
        task = next(item for item in state.queue if item.task_id == task_id)
        if task.status is TaskStatus.VERIFIED:
            return False
        if task.status not in {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.PAUSED}:
            return False
        task.status = TaskStatus.VERIFIED
        task.completed_at = self.clock()
        task.failure_reason = ""
        if state.current_task_id == task_id:
            state.current_task_id = None
        state.iteration += 1
        state.last_verified_at = self.clock()
        state.last_result = {"task_id": task_id, "status": TaskStatus.VERIFIED.value, "evidence": list(evidence)}
        self._save(state, {"event": "task_reconciled_verified", "task_id": task_id, "evidence": list(evidence)})
        return True

    def record_failure(self, task_id: str, status: TaskStatus, reason: str) -> None:
        if status not in {TaskStatus.REJECTED, TaskStatus.ROLLED_BACK, TaskStatus.PAUSED}:
            raise ValueError("failure status must be rejected, rolled_back, or paused")
        state = self._state()
        task = next(item for item in state.queue if item.task_id == task_id)
        task.status = status
        task.failure_reason = str(reason)
        task.completed_at = self.clock()
        state.current_task_id = None
        state.last_result = {"task_id": task_id, "status": status.value, "reason": str(reason)}
        self._save(state, {"event": "task_failed", "task_id": task_id, "status": status.value, "reason": str(reason)})

    def retry(self, task_id: str, reason: str) -> bool:
        state = self._state()
        task = next(item for item in state.queue if item.task_id == task_id)
        if task.status not in {TaskStatus.REJECTED, TaskStatus.ROLLED_BACK, TaskStatus.PAUSED}:
            return False
        if task.attempts >= self.policy.max_task_attempts:
            return False
        task.status = TaskStatus.QUEUED
        task.completed_at = None
        task.failure_reason = str(reason)
        state.current_task_id = None
        self._save(state, {"event": "task_retry_queued", "task_id": task_id, "attempt": task.attempts, "reason": str(reason)})
        return True

    def can_enqueue_follow_up(self) -> bool:
        return self._state().follow_ups_enqueued < self.policy.max_follow_ups

    def mark_follow_up_enqueued(self) -> None:
        state = self._state()
        if state.follow_ups_enqueued >= self.policy.max_follow_ups:
            raise RuntimeError("follow-up task budget exhausted")
        state.follow_ups_enqueued += 1
        self._save(state, {"event": "follow_up_reserved"})

    def pause(self, reason: str) -> None:
        state = self._state()
        state.paused = True
        state.last_result = {"status": TaskStatus.PAUSED.value, "reason": str(reason)}
        self._save(state, {"event": "paused", "reason": str(reason)})

    def resume(self) -> None:
        state = self._state()
        state.paused = False
        state.stopped = False
        state.stop_reason = ""
        self._save(state, {"event": "resumed"})

    def stop(self, reason: str) -> None:
        state = self._state()
        state.stopped = True
        state.stop_reason = str(reason)
        self._save(state, {"event": "stopped", "reason": str(reason)})

    def status(self) -> dict[str, object]:
        state = self._state()
        if self._budget_exhausted(state) and not state.paused:
            state.paused = True
            self._save(state, {"event": "budget_paused"})
        return {
            "paused": state.paused,
            "stopped": state.stopped,
            "stop_reason": state.stop_reason,
            "current_task_id": state.current_task_id,
            "queue_length": sum(item.status is TaskStatus.QUEUED for item in state.queue),
            "iteration": state.iteration,
            "follow_ups_enqueued": state.follow_ups_enqueued,
            "last_result": state.last_result,
        }
