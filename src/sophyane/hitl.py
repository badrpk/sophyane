"""Human-in-the-loop approval queue for sensitive agent actions."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

HITL_DIR = Path.home() / ".local" / "state" / "sophyane" / "hitl"
QUEUE = HITL_DIR / "queue.json"


def _load() -> list[dict[str, Any]]:
    HITL_DIR.mkdir(parents=True, exist_ok=True)
    if not QUEUE.exists():
        return []
    try:
        data = json.loads(QUEUE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _save(items: list[dict[str, Any]]) -> None:
    HITL_DIR.mkdir(parents=True, exist_ok=True)
    QUEUE.write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")


def request_approval(action: str, detail: str = "", *, risk: str = "medium") -> dict[str, Any]:
    items = _load()
    item = {
        "id": uuid.uuid4().hex[:12],
        "action": action,
        "detail": detail[:4000],
        "risk": risk,
        "status": "pending",
        "created_at": time.time(),
        "resolved_at": None,
    }
    items.append(item)
    _save(items)
    return {"ok": True, "request": item, "message": "Awaiting human approval (sophyane --approve ID)"}


def list_pending() -> dict[str, Any]:
    items = [i for i in _load() if i.get("status") == "pending"]
    return {"ok": True, "pending": items, "count": len(items)}


def resolve(request_id: str, *, approve: bool, note: str = "") -> dict[str, Any]:
    items = _load()
    found = None
    for item in items:
        if item.get("id") == request_id:
            item["status"] = "approved" if approve else "denied"
            item["resolved_at"] = time.time()
            item["note"] = note
            found = item
            break
    if not found:
        return {"ok": False, "error": "request not found"}
    _save(items)
    return {"ok": True, "request": found}


def is_approved(request_id: str) -> bool:
    for item in _load():
        if item.get("id") == request_id:
            return item.get("status") == "approved"
    return False
