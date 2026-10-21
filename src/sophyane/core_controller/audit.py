"""Append-only audit storage with bounded, restart-safe recovery."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .models import AuditEvent, ModeName


_SECRET_KEYS = {"api_key", "apikey", "authorization", "password", "secret", "token"}
_TERMINAL_EVENTS = {"execution_completed", "terminal_failure", "recovery_required"}


def _safe(value: Any, *, key: str = "") -> Any:
    if key.lower() in _SECRET_KEYS or any(part in key.lower() for part in _SECRET_KEYS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _safe(v, key=str(k)) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (tuple, list)):
        return [_safe(item) for item in value]
    if isinstance(value, str) and key.lower() in {"error", "reason", "message"}:
        return value[:1000]
    return value


def _event_from_dict(payload: dict[str, Any]) -> AuditEvent:
    mode = payload.get("mode")
    return AuditEvent(
        trace_id=str(payload.get("trace_id", "")),
        event_type=str(payload.get("event_type", "")),
        mode=ModeName(mode) if mode else None,
        disposition=str(payload.get("disposition", "")),
        data=payload.get("data") if isinstance(payload.get("data"), dict) else {},
    )


class AuditStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, event: AuditEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = _safe(event.to_dict())
        line = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def _read_all(self) -> tuple[AuditEvent, ...]:
        if not self.path.is_file():
            return ()
        events: list[AuditEvent] = []
        try:
            with self.path.open(encoding="utf-8") as handle:
                for line in handle:
                    try:
                        payload = json.loads(line)
                        if isinstance(payload, dict):
                            events.append(_event_from_dict(payload))
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
        except OSError:
            return ()
        return tuple(events)

    def read(self, trace_id: str) -> tuple[AuditEvent, ...]:
        return tuple(event for event in self._read_all() if event.trace_id == trace_id)

    def recover_inflight(self) -> tuple[str, ...]:
        grouped: dict[str, list[AuditEvent]] = {}
        for event in self._read_all():
            grouped.setdefault(event.trace_id, []).append(event)
        recovered: list[str] = []
        for trace_id, events in grouped.items():
            if any(event.event_type in _TERMINAL_EVENTS for event in events):
                continue
            last = events[-1]
            self.append(AuditEvent(
                trace_id=trace_id,
                event_type="recovery_required",
                mode=last.mode,
                disposition="needs_review",
                data={"reason": "in-flight request unknown after restart"},
            ))
            recovered.append(trace_id)
        return tuple(recovered)
