"""Atomic durable liveness state for the continuous RSI worker."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HeartbeatRecord:
    worker_id: str
    pid: int
    state: str
    started_at: float
    last_tick_at: float
    current_task_id: str | None = None
    last_error: str = ""
    restart_count: int = 0
    schema_version: int = 1

    def is_stale(self, now: float, threshold: float) -> bool:
        if threshold < 0:
            raise ValueError("heartbeat threshold must be non-negative")
        return float(now) - self.last_tick_at >= threshold


class HeartbeatStore:
    def __init__(self, path: Path):
        self.path = Path(path).expanduser()
        if self.path.name in {"", ".", ".."}:
            raise ValueError("invalid heartbeat state path")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> HeartbeatRecord:
        try:
            raw: Any = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or int(raw.get("schema_version", 0)) != 1:
                raise ValueError("unsupported schema")
            return HeartbeatRecord(
                worker_id=str(raw["worker_id"]),
                pid=int(raw["pid"]),
                state=str(raw["state"]),
                started_at=float(raw["started_at"]),
                last_tick_at=float(raw["last_tick_at"]),
                current_task_id=raw.get("current_task_id"),
                last_error=str(raw.get("last_error", "")),
                restart_count=int(raw.get("restart_count", 0)),
                schema_version=1,
            )
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid heartbeat state: {error}") from error

    def save(self, record: HeartbeatRecord) -> None:
        payload = asdict(record)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def touch(self, **updates: object) -> HeartbeatRecord:
        allowed = {
            "worker_id", "pid", "state", "started_at", "last_tick_at",
            "current_task_id", "last_error", "restart_count",
        }
        unknown = set(updates) - allowed
        if unknown:
            raise ValueError(f"unknown heartbeat fields: {sorted(unknown)}")
        updated = replace(self.load(), **updates)
        self.save(updated)
        return updated
