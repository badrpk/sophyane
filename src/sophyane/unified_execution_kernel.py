"""Unified capability execution kernel for Sophyane."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

CapabilityHandler = Callable[["ExecutionRequest"], "ExecutionResult | None"]


@dataclass(frozen=True)
class ExecutionRequest:
    text: str
    workspace: str
    request_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionResult:
    handled: bool
    ok: bool
    capability: str
    output: str
    evidence: dict[str, Any]
    started_at: float
    finished_at: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_text(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


@dataclass(frozen=True)
class CapabilitySpec:
    capability_id: str
    description: str
    priority: int
    handler: CapabilityHandler


class CapabilityRegistry:
    def __init__(self) -> None:
        self._items: dict[str, CapabilitySpec] = {}
        self._lock = threading.RLock()

    def register(
        self,
        capability_id: str,
        handler: CapabilityHandler,
        *,
        description: str = "",
        priority: int = 100,
    ) -> None:
        if not capability_id or not callable(handler):
            raise ValueError("A capability requires an ID and callable handler.")

        with self._lock:
            self._items[capability_id] = CapabilitySpec(
                capability_id=capability_id,
                description=description,
                priority=priority,
                handler=handler,
            )

    def ordered(self) -> list[CapabilitySpec]:
        with self._lock:
            return sorted(
                self._items.values(),
                key=lambda item: (item.priority, item.capability_id),
            )

    def catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "capability": item.capability_id,
                "description": item.description,
                "priority": item.priority,
            }
            for item in self.ordered()
        ]

    def execute(self, request: ExecutionRequest) -> ExecutionResult | None:
        for spec in self.ordered():
            result = spec.handler(request)
            if result is not None and result.handled:
                return result
        return None


_REGISTRY = CapabilityRegistry()
_INITIALIZED = False
_INIT_LOCK = threading.Lock()


def _coding_handler(request: ExecutionRequest) -> ExecutionResult | None:
    from sophyane.local_coding_capability import try_coding_request

    started = time.time()
    result = try_coding_request(
        request.text,
        workspace=request.workspace,
    )

    if result is None:
        return None

    finished = time.time()

    return ExecutionResult(
        handled=result.handled,
        ok=result.ok,
        capability=result.capability,
        output=result.to_text(),
        evidence=result.to_dict(),
        started_at=started,
        finished_at=finished,
    )


def _existing_deterministic_handler(
    request: ExecutionRequest,
) -> ExecutionResult | None:
    try:
        from sophyane.capability_executors import (
            execute_deterministic_capability,
        )
    except Exception:
        return None

    started = time.time()
    result = execute_deterministic_capability(
        request.text,
        workspace=request.workspace,
    )

    if result is None:
        return None

    finished = time.time()

    return ExecutionResult(
        handled=True,
        ok=bool(result.ok),
        capability=str(result.capability_id),
        output=str(result.text),
        evidence={
            "data": result.data,
            "deterministic": result.deterministic,
            "provider_bypassed": result.provider_bypassed,
        },
        started_at=started,
        finished_at=finished,
    )


def initialize_registry() -> CapabilityRegistry:
    global _INITIALIZED

    if _INITIALIZED:
        return _REGISTRY

    with _INIT_LOCK:
        if _INITIALIZED:
            return _REGISTRY

        _REGISTRY.register(
            "development.local_coding",
            _coding_handler,
            description=(
                "Create, validate, compile and optionally run bounded local "
                "C++ and Python artifacts."
            ),
            priority=10,
        )

        _REGISTRY.register(
            "legacy.deterministic_capabilities",
            _existing_deterministic_handler,
            description=(
                "Existing grounded deterministic Sophyane capabilities."
            ),
            priority=20,
        )

        _INITIALIZED = True

    return _REGISTRY


def execute_request(
    text: str,
    *,
    workspace: str | Path | None = None,
    request_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> ExecutionResult | None:
    root = Path(workspace or Path.cwd()).expanduser().resolve()

    request = ExecutionRequest(
        text=str(text or "").strip(),
        workspace=str(root),
        request_id=request_id,
        metadata=metadata or {},
    )

    if not request.text:
        return None

    return initialize_registry().execute(request)


def execute_text(
    text: str,
    *,
    workspace: str | Path | None = None,
) -> str | None:
    result = execute_request(text, workspace=workspace)
    return result.output if result is not None else None


def capability_catalog() -> list[dict[str, Any]]:
    return initialize_registry().catalog()


__all__ = [
    "CapabilityRegistry",
    "CapabilitySpec",
    "ExecutionRequest",
    "ExecutionResult",
    "capability_catalog",
    "execute_request",
    "execute_text",
    "initialize_registry",
]
