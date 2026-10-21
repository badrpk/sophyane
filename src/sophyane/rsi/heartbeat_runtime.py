"""Heartbeat-driven worker and watchdog for continuous RSI."""

from __future__ import annotations

import os
import time
import uuid
from typing import Callable

from .heartbeat import HeartbeatRecord, HeartbeatStore


class ContinuousRSIWorker:
    def __init__(self, runtime, heartbeat: HeartbeatStore, source=None, *, context_factory: Callable[[], object] | None = None, clock=time.time):
        self.runtime = runtime
        self.heartbeat = heartbeat
        self.source = source
        self.context_factory = context_factory
        self.clock = clock

    def _touch(self, **updates):
        try:
            return self.heartbeat.touch(last_tick_at=self.clock(), **updates)
        except ValueError:
            if self.heartbeat.path.exists():
                raise
            now = self.clock()
            record = HeartbeatRecord(
                worker_id=f"rsi-{uuid.uuid4().hex}",
                pid=os.getpid(),
                state="starting",
                started_at=now,
                last_tick_at=now,
            )
            record = HeartbeatRecord(**{**record.__dict__, **updates, "last_tick_at": now})
            self.heartbeat.save(record)
            return record

    def run_once(self) -> dict[str, object]:
        status = self.runtime.status()
        if status.get("stopped") or status.get("paused"):
            state = "stopped" if status.get("stopped") else "paused"
            self._touch(state=state)
            return {"status": state}
        try:
            self._touch(state="running", last_error="")
        except Exception as error:
            return {"status": "paused", "reason": f"heartbeat unavailable: {error}"}
        try:
            cycle_warning = ""
            if status.get("queue_length", 0) == 0 and self.source is not None and self.context_factory is not None:
                context = self.context_factory()
                if context is None:
                    cycle_warning = "no frozen experiment plan configured"
                    self._touch(state="waiting", last_error=cycle_warning)
                else:
                    proposal = self.source.propose(context)
                    if proposal.accepted and proposal.task is not None:
                        proposal.task.review_status = (
                            "approved" if proposal.review_outcome == "approved" else "pending"
                        )
                        queued = self.runtime.scheduler.enqueue(proposal.task)
                        if not queued:
                            cycle_warning = "scheduler rejected proposed task"
                            self._touch(state="waiting", last_error=cycle_warning)
                        else:
                            store = getattr(self.runtime.scheduler, "store", None)
                            if store is not None:
                                store.append_event({
                                    "event": "proposal_provenance",
                                    "task_id": proposal.task.task_id,
                                    "generator": proposal.generator or "unknown",
                                    "reviewers": list(proposal.reviewers),
                                    "review_outcome": proposal.review_outcome or "unreviewed",
                                })
                    elif not proposal.accepted:
                        cycle_warning = f"task proposal rejected: {proposal.reason}"
                        self._touch(state="waiting", last_error=cycle_warning)
            result = self.runtime.tick()
            result_status = str(result.get("status", "")).lower()
            result_error = str(result.get("reason", ""))
            current_error = cycle_warning
            if result_status in {"paused", "error"} and result_error:
                current_error = result_error
            self._touch(state="waiting", current_task_id=result.get("task_id"), last_error=current_error)
            return result
        except Exception as error:
            self._touch(state="error", last_error=str(error)[:1000])
            return {"status": "paused", "reason": str(error)}


class RSIWatchdog:
    def __init__(self, heartbeat: HeartbeatStore, start_worker, scheduler, stale_seconds: float, *, clock=time.time):
        self.heartbeat = heartbeat
        self.start_worker = start_worker
        self.scheduler = scheduler
        self.stale_seconds = max(1.0, float(stale_seconds))
        self.clock = clock

    def check(self) -> dict[str, object]:
        status = self.scheduler.status()
        if status.get("paused") or status.get("stopped"):
            return {"status": "suppressed", "reason": "durable pause/stop"}
        try:
            record = self.heartbeat.load()
        except ValueError as error:
            return {"status": "error", "reason": str(error)}
        if not record.is_stale(self.clock(), self.stale_seconds):
            return {"status": "healthy", "restart_count": record.restart_count}
        updated = self.heartbeat.touch(
            state="restarting",
            last_tick_at=self.clock(),
            last_error="stale heartbeat; restarting worker",
            restart_count=record.restart_count + 1,
        )
        try:
            self.start_worker()
        except Exception as error:
            self.heartbeat.touch(state="error", last_error=str(error)[:1000])
            return {"status": "error", "reason": str(error)}
        return {"status": "restarted", "restart_count": updated.restart_count}
