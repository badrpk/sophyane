"""Common adapter contract for Badrpk ecosystem peers.

This module intentionally separates:

    discovery
    execution readiness
    invocation

A repository being discoverable on GitHub is not permission to execute it.
"""
from __future__ import annotations

import threading

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable


PeerInvoker = Callable[
    [str, str, str],
    "PeerCapabilityResult",
]


@dataclass(frozen=True)
class PeerCapabilityRequest:
    repository: str
    capability: str
    objective: str
    workspace: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PeerCapabilityResult:
    handled: bool
    ok: bool
    repository: str
    capability: str
    output: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PeerAdapterSpec:
    repository: str
    capabilities: tuple[str, ...]
    invoker: PeerInvoker


class PeerCapabilityRegistry:
    def __init__(self) -> None:
        self._items: dict[
            str,
            PeerAdapterSpec,
        ] = {}

        self._lock = (
            threading.RLock()
        )

    def register(
        self,
        *,
        repository: str,
        capabilities: tuple[str, ...],
        invoker: PeerInvoker,
    ) -> None:
        repository = str(
            repository
            or ""
        ).strip().casefold()

        if not repository:
            raise ValueError(
                "peer repository is required"
            )

        if not callable(invoker):
            raise ValueError(
                "peer invoker must be callable"
            )

        normalized = tuple(
            sorted({
                str(item)
                .strip()
                .casefold()
                for item in capabilities
                if str(item).strip()
            })
        )

        with self._lock:
            self._items[
                repository
            ] = PeerAdapterSpec(
                repository=repository,
                capabilities=normalized,
                invoker=invoker,
            )

    def repositories(
        self,
    ) -> tuple[str, ...]:
        with self._lock:
            return tuple(
                sorted(
                    self._items
                )
            )

    def supports(
        self,
        *,
        repository: str,
        capability: str = "",
    ) -> bool:
        repository = str(
            repository
            or ""
        ).strip().casefold()

        capability = str(
            capability
            or ""
        ).strip().casefold()

        with self._lock:
            spec = self._items.get(
                repository
            )

        if spec is None:
            return False

        if not capability:
            return True

        return (
            capability
            in spec.capabilities
        )

    def invoke(
        self,
        request: PeerCapabilityRequest,
    ) -> PeerCapabilityResult:
        repository = str(
            request.repository
            or ""
        ).strip().casefold()

        capability = str(
            request.capability
            or ""
        ).strip().casefold()

        with self._lock:
            spec = self._items.get(
                repository
            )

        if spec is None:
            return PeerCapabilityResult(
                handled=False,
                ok=False,
                repository=repository,
                capability=capability,
                output="",
                evidence={
                    "reason": (
                        "PEER_ADAPTER_UNAVAILABLE"
                    ),
                },
            )

        if (
            capability
            and capability
            not in spec.capabilities
        ):
            return PeerCapabilityResult(
                handled=False,
                ok=False,
                repository=repository,
                capability=capability,
                output="",
                evidence={
                    "reason": (
                        "PEER_CAPABILITY_UNSUPPORTED"
                    ),
                },
            )

        result = spec.invoker(
            capability,
            request.objective,
            request.workspace,
        )

        if not isinstance(
            result,
            PeerCapabilityResult,
        ):
            raise TypeError(
                "peer invoker returned invalid result"
            )

        return result


_REGISTRY = PeerCapabilityRegistry()


def register_peer_adapter(
    *,
    repository: str,
    capabilities: tuple[str, ...],
    invoker: PeerInvoker,
) -> None:
    _REGISTRY.register(
        repository=repository,
        capabilities=capabilities,
        invoker=invoker,
    )


def invoke_peer_capability(
    *,
    repository: str,
    capability: str,
    objective: str,
    workspace: str | Path,
) -> PeerCapabilityResult:
    return _REGISTRY.invoke(
        PeerCapabilityRequest(
            repository=repository,
            capability=capability,
            objective=str(
                objective
                or ""
            ),
            workspace=str(
                Path(workspace)
                .expanduser()
                .resolve()
            ),
        )
    )


def peer_adapter_catalog(
) -> tuple[str, ...]:
    return _REGISTRY.repositories()


__all__ = [
    "PeerAdapterSpec",
    "PeerCapabilityRegistry",
    "PeerCapabilityRequest",
    "PeerCapabilityResult",
    "invoke_peer_capability",
    "peer_adapter_catalog",
    "register_peer_adapter",
]
