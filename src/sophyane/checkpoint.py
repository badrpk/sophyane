"""Checkpoint / resume for long-running agent tasks."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

CP_DIR = Path.home() / ".local" / "state" / "sophyane" / "checkpoints"


def save_checkpoint(name: str, state: dict[str, Any], *, task_id: str | None = None) -> dict[str, Any]:
    CP_DIR.mkdir(parents=True, exist_ok=True)
    task_id = task_id or uuid.uuid4().hex[:12]
    path = CP_DIR / f"{task_id}.json"
    payload = {
        "task_id": task_id,
        "name": name,
        "state": state,
        "updated_at": time.time(),
        "version": 1,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "task_id": task_id, "path": str(path)}


def load_checkpoint(task_id: str) -> dict[str, Any]:
    path = CP_DIR / f"{task_id}.json"
    if not path.exists():
        return {"ok": False, "error": "not found"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {"ok": True, **data}
    except json.JSONDecodeError as error:
        return {"ok": False, "error": str(error)}


def list_checkpoints() -> dict[str, Any]:
    CP_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for path in sorted(CP_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items.append(
                {
                    "task_id": data.get("task_id") or path.stem,
                    "name": data.get("name"),
                    "updated_at": data.get("updated_at"),
                }
            )
        except json.JSONDecodeError:
            items.append({"task_id": path.stem})
    return {"ok": True, "checkpoints": items, "count": len(items)}


def delete_checkpoint(task_id: str) -> dict[str, Any]:
    path = CP_DIR / f"{task_id}.json"
    if path.exists():
        path.unlink()
        return {"ok": True, "deleted": task_id}
    return {"ok": False, "error": "not found"}
