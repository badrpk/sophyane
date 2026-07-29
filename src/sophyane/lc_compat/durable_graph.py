"""LangGraph-like durable execution helpers on top of sophyane.graph_runtime."""
from __future__ import annotations
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sophyane.graph_runtime import DurableStore, GraphInterrupt, StateGraph

STATE_DIR = Path.home() / ".local/state/sophyane/checkpoints"

@dataclass
class ThreadState:
    thread_id: str
    checkpoint_id: str | None = None
    values: dict[str, Any] = field(default_factory=dict)
    next_nodes: list[str] = field(default_factory=list)
    status: str = "idle"  # idle|running|interrupted|done|error

class DurableExecutor:
    """thread_id + checkpoint + interrupt/resume facade."""

    def __init__(self, graph: StateGraph, store: DurableStore | None = None) -> None:
        self.graph = graph.compile()
        self.store = store or DurableStore()
        STATE_DIR.mkdir(parents=True, exist_ok=True)

    def invoke(
        self,
        initial: dict[str, Any],
        *,
        thread_id: str | None = None,
        checkpoint_id: str | None = None,
        resume: bool = False,
    ) -> ThreadState:
        tid = thread_id or str(uuid.uuid4())
        ckpt = checkpoint_id or f"ckpt_{tid}_{int(time.time()*1000)}"
        ts = ThreadState(thread_id=tid, checkpoint_id=ckpt, status="running")
        state_in = dict(initial)
        try:
            result = self.graph.invoke(
                state_in,
                checkpoint_id=ckpt,
                resume=resume,
                ignore_interrupt_once=resume,
                return_result=True,
            )
            if hasattr(result, "state"):
                ts.values = dict(result.state)
                ts.next_nodes = [result.next_node] if getattr(result, "next_node", None) else []
                ts.status = "done" if getattr(result, "completed", True) else "running"
                if getattr(result, "checkpoint_id", None):
                    ts.checkpoint_id = result.checkpoint_id
            else:
                ts.values = dict(result)
                ts.status = "done"
        except GraphInterrupt as gi:
            ts.status = "interrupted"
            ts.next_nodes = [gi.node]
            ts.checkpoint_id = gi.checkpoint_id or ckpt
            # Prefer state from DurableStore checkpoint written by graph_runtime
            saved = self.store.get("checkpoint", ts.checkpoint_id) if ts.checkpoint_id else None
            if isinstance(saved, dict) and isinstance(saved.get("state"), dict):
                ts.values = dict(saved["state"])
            else:
                ts.values = dict(state_in)
            self._save_thread(ts)
            return ts
        self._save_thread(ts)
        return ts

    def resume(self, thread_id: str, update: dict[str, Any] | None = None) -> ThreadState:
        ts = self._load_thread(thread_id)
        state = {**ts.values, **(update or {})}
        return self.invoke(
            state,
            thread_id=thread_id,
            checkpoint_id=ts.checkpoint_id,
            resume=True,
        )

    def _save_thread(self, ts: ThreadState) -> None:
        path = STATE_DIR / f"{ts.thread_id}.json"
        path.write_text(
            json.dumps(
                {
                    "thread_id": ts.thread_id,
                    "checkpoint_id": ts.checkpoint_id,
                    "values": ts.values,
                    "next_nodes": ts.next_nodes,
                    "status": ts.status,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        self.store.put("thread", ts.thread_id, {
            "checkpoint_id": ts.checkpoint_id,
            "values": ts.values,
            "next_nodes": ts.next_nodes,
            "status": ts.status,
        })

    def _load_thread(self, thread_id: str) -> ThreadState:
        path = STATE_DIR / f"{thread_id}.json"
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            return ThreadState(**data)
        saved = self.store.get("thread", thread_id)
        if not saved:
            raise KeyError(f"unknown thread: {thread_id}")
        return ThreadState(thread_id=thread_id, **saved)
