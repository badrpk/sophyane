"""Token / cost / time budgets for agent runs."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

STATE = Path.home() / ".local" / "state" / "sophyane" / "budget.json"

_DEFAULT = {
    "token_budget": 500_000,
    "tokens_used": 0,
    "cost_budget_usd": 10.0,
    "cost_used_usd": 0.0,
    "time_budget_sec": 3600,
}


def _load() -> dict[str, Any]:
    if not STATE.exists():
        data = dict(_DEFAULT)
        data["updated_at"] = time.time()
        return data
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
        for k, v in _DEFAULT.items():
            data.setdefault(k, v)
        return data
    except json.JSONDecodeError:
        data = dict(_DEFAULT)
        data["updated_at"] = time.time()
        return data


def _save(data: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = time.time()
    STATE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def configure(
    *,
    tokens: int | None = None,
    cost_usd: float | None = None,
    time_sec: int | None = None,
) -> dict[str, Any]:
    data = _load()
    if tokens is not None:
        data["token_budget"] = int(tokens)
    if cost_usd is not None:
        data["cost_budget_usd"] = float(cost_usd)
    if time_sec is not None:
        data["time_budget_sec"] = int(time_sec)
    _save(data)
    return status()


def record_usage(*, tokens: int = 0, cost_usd: float = 0.0) -> dict[str, Any]:
    data = _load()
    data["tokens_used"] = int(data.get("tokens_used") or 0) + max(0, int(tokens))
    data["cost_used_usd"] = float(data.get("cost_used_usd") or 0) + max(0.0, float(cost_usd))
    _save(data)
    return status()


def reset_usage() -> dict[str, Any]:
    data = _load()
    data["tokens_used"] = 0
    data["cost_used_usd"] = 0.0
    _save(data)
    return status()


def status() -> dict[str, Any]:
    data = _load()
    tb = float(data.get("token_budget") or 1)
    cb = float(data.get("cost_budget_usd") or 1)
    tu = float(data.get("tokens_used") or 0)
    cu = float(data.get("cost_used_usd") or 0)
    ok = tu < tb and cu < cb
    return {
        "ok": ok,
        "tokens_used": int(tu),
        "token_budget": int(tb),
        "tokens_remaining": max(0, int(tb - tu)),
        "cost_used_usd": round(cu, 4),
        "cost_budget_usd": cb,
        "time_budget_sec": data.get("time_budget_sec"),
        "exhausted": not ok,
    }


def allow_request(*, est_tokens: int = 1000) -> tuple[bool, str]:
    st = status()
    if st["exhausted"]:
        return False, "budget exhausted"
    if st["tokens_remaining"] < est_tokens:
        return False, "insufficient token budget"
    return True, "ok"
