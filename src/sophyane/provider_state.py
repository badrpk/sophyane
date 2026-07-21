"""Thread-safe process-local provider dispatch state.

All provider selection paths publish here; UI heartbeats read from the same source.
"""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
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
    """Publish one or more provider-dispatch fields and return a snapshot."""
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
    """Return the complete current dispatch state."""
    with _LOCK:
        return asdict(_STATE)


def get_active_provider() -> str:
    """Return the active provider ID through the stable public API."""
    with _LOCK:
        return _STATE.active


def set_active_provider(provider: str, mode: str = "active") -> dict[str, Any]:
    """Set the active provider while preserving the configured primary provider.

    This compatibility API is used by audits, plugins, and integrations. Runtime
    code may continue using :func:`publish` when updating multiple fields.
    """
    return publish(active=provider, mode=mode)


__all__ = [
    "DispatchState",
    "get_active_provider",
    "publish",
    "set_active_provider",
    "snapshot",
]
