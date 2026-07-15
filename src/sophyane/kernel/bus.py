"""In-process publish/subscribe bus for Sophyane AI Kernel modules."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any, Callable


@dataclass
class KernelEvent:
    topic: str
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "kernel"
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class KernelBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[[KernelEvent], None]]] = defaultdict(list)
        self._lock = threading.Lock()
        self._history: list[KernelEvent] = []
        self._max_history = 200

    def subscribe(self, topic: str, handler: Callable[[KernelEvent], None]) -> None:
        with self._lock:
            self._subs[topic].append(handler)

    def publish(self, topic: str, payload: dict[str, Any] | None = None, source: str = "kernel") -> KernelEvent:
        event = KernelEvent(topic=topic, payload=payload or {}, source=source)
        with self._lock:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history :]
            handlers = list(self._subs.get(topic, []))
            handlers += list(self._subs.get("*", []))
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                # Kernel bus must not crash the supervisor.
                pass
        return event

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            items = self._history[-limit:]
        return [item.to_dict() for item in items]
