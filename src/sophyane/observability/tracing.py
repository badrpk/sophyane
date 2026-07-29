"""Local run traces (LangSmith-lite)."""
from __future__ import annotations
import json
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterator

TRACE_DIR = Path.home() / ".local/state/sophyane/traces"
TRACE_DIR.mkdir(parents=True, exist_ok=True)

@dataclass
class Span:
    name: str
    run_id: str
    parent_id: str | None = None
    start: float = field(default_factory=time.time)
    end: float | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def latency_ms(self) -> float:
        if self.end is None:
            return 0.0
        return (self.end - self.start) * 1000

@dataclass
class Trace:
    trace_id: str
    spans: list[Span] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def save(self) -> Path:
        path = TRACE_DIR / f"{self.trace_id}.json"
        path.write_text(
            json.dumps({"trace_id": self.trace_id, "tags": self.tags, "spans": [asdict(s) for s in self.spans]}, indent=2),
            encoding="utf-8",
        )
        return path

_active: Trace | None = None

def get_active_trace() -> Trace | None:
    return _active

@contextmanager
def start_trace(name: str = "run", tags: list[str] | None = None) -> Iterator[Trace]:
    global _active
    tr = Trace(trace_id=str(uuid.uuid4()), tags=tags or [])
    root = Span(name=name, run_id=tr.trace_id)
    tr.spans.append(root)
    prev = _active
    _active = tr
    try:
        yield tr
    finally:
        root.end = time.time()
        tr.save()
        _active = prev

@contextmanager
def span(name: str, inputs: dict[str, Any] | None = None) -> Iterator[Span]:
    tr = _active
    sp = Span(name=name, run_id=str(uuid.uuid4()), parent_id=tr.trace_id if tr else None, inputs=inputs or {})
    try:
        yield sp
    except Exception as e:
        sp.error = str(e)
        sp.end = time.time()
        if tr:
            tr.spans.append(sp)
        raise
    else:
        sp.end = time.time()
        if tr:
            tr.spans.append(sp)

def list_traces(limit: int = 20) -> list[Path]:
    files = sorted(TRACE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]
