"""Agent permission profiles: read / write / network / exec levels."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STATE = Path.home() / ".local" / "state" / "sophyane" / "permissions.json"

PROFILES = {
    "readonly": {"read": True, "write": False, "network": False, "exec": False, "hitl_writes": True},
    "workspace": {"read": True, "write": True, "network": False, "exec": True, "hitl_writes": False},
    "network": {"read": True, "write": True, "network": True, "exec": True, "hitl_writes": False},
    "strict": {"read": True, "write": False, "network": False, "exec": False, "hitl_writes": True},
    "full": {"read": True, "write": True, "network": True, "exec": True, "hitl_writes": False},
}


def get_profile() -> dict[str, Any]:
    name = "workspace"
    if STATE.exists():
        try:
            data = json.loads(STATE.read_text(encoding="utf-8"))
            name = str(data.get("profile") or "workspace")
        except json.JSONDecodeError:
            pass
    perms = dict(PROFILES.get(name) or PROFILES["workspace"])
    return {"ok": True, "profile": name, "permissions": perms, "available": sorted(PROFILES)}


def set_profile(name: str) -> dict[str, Any]:
    if name not in PROFILES:
        return {"ok": False, "error": f"unknown profile: {name}", "available": sorted(PROFILES)}
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"profile": name}, indent=2) + "\n", encoding="utf-8")
    return get_profile()


def allows(action: str) -> bool:
    perms = get_profile()["permissions"]
    return bool(perms.get(action))
