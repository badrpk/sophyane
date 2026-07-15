"""Lightweight run traces / spans for agent observability."""

from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

TRACE_DIR = Path.home() / ".local" / "state" / "sophyane" / "traces"


def start_run(name: str = "agent", *, meta: dict[str, Any] | None = None) -> str:
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex[:16]
    path = TRACE_DIR / f"{run_id}.jsonl"
    _append(path, {"type": "run_start", "run_id": run_id, "name": name, "ts": time.time(), "meta": meta or {}})
    return run_id


def span(run_id: str, name: str, **fields: Any) -> None:
    path = TRACE_DIR / f"{run_id}.jsonl"
    _append(path, {"type": "span", "run_id": run_id, "name": name, "ts": time.time(), **fields})


def end_run(run_id: str, *, ok: bool = True, summary: str = "") -> None:
    path = TRACE_DIR / f"{run_id}.jsonl"
    _append(path, {"type": "run_end", "run_id": run_id, "ok": ok, "summary": summary, "ts": time.time()})


def _append(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


@contextmanager
def traced(name: str, **meta: Any) -> Iterator[str]:
    run_id = start_run(name, meta=meta)
    try:
        yield run_id
        end_run(run_id, ok=True)
    except Exception as error:  # noqa: BLE001
        end_run(run_id, ok=False, summary=str(error))
        raise


def list_traces(limit: int = 20) -> dict[str, Any]:
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(TRACE_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    items = []
    for f in files:
        try:
            first = f.read_text(encoding="utf-8", errors="replace").splitlines()[0]
            items.append({"run_id": f.stem, "start": json.loads(first), "path": str(f)})
        except Exception:  # noqa: BLE001
            items.append({"run_id": f.stem, "path": str(f)})
    return {"ok": True, "traces": items, "count": len(items)}


def get_trace(run_id: str) -> dict[str, Any]:
    path = TRACE_DIR / f"{run_id}.jsonl"
    if not path.exists():
        return {"ok": False, "error": "not found"}
    events = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return {"ok": True, "run_id": run_id, "events": events}
