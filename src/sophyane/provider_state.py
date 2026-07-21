"""Thread-safe process-local provider dispatch state.

All provider selection paths publish here; UI heartbeats read from the same source.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, asdict
from typing import Any

_LOCK = threading.RLock()

@dataclass
class DispatchState:
    primary: str = ""
    active: str = ""
    mode: str = "idle"
    sequence: int = 0
    updated_at: float = 0.0

_STATE = DispatchState()


def publish(*, primary: str | None = None, active: str | None = None, mode: str | None = None) -> dict[str, Any]:
    with _LOCK:
        if primary is not None:
            _STATE.primary = str(primary).strip().lower()
        if active is not None:
            _STATE.active = str(active).strip().lower()
        if mode is not None:
            _STATE.mode = str(mode).strip().lower()
        _STATE.sequence += 1
        _STATE.updated_at = time.time()
        return asdict(_STATE)


def snapshot() -> dict[str, Any]:
    with _LOCK:
        return asdict(_STATE)
