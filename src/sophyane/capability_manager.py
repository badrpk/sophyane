"""Capability discovery and selection for Sophyane runtimes."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


CapabilityHandler = Callable[..., Any]


def _normalize(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _normalize_tags(values: Iterable[str]) -> frozenset[str]:
    return frozenset(
        normalized
        for value in values
        if (normalized := _normalize(value))
    )


@dataclass(frozen=True)
class Capability:
    """Description of one executable Sophyane capability."""

    name: str
    description: str
    supports: frozenset[str]
    priority: int = 50
    enabled: bool = True
    provider: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        name = _normalize(self.name)
        if not name:
            raise ValueError("capability name must not be empty")

        if not self.supports:
            raise ValueError("capability must support at least one task")

        object.__setattr__(self, "name", name)
        object.__setattr__(self, "description", self.description.strip())
        object.__setattr__(self, "supports", _normalize_tags(self.supports))
        object.__setattr__(self, "provider", _normalize(self.provider))
        object.__setattr__(self, "priority", int(self.priority))
        object.__setattr__(self, "enabled", bool(self.enabled))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["supports"] = sorted(self.supports)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Capability":
        return cls(
            name=str(payload["name"]),
            description=str(payload.get("description", "")),
            supports=frozenset(payload.get("supports", ())),
            priority=int(payload.get("priority", 50)),
            enabled=bool(payload.get("enabled", True)),
            provider=str(payload.get("provider", "")),
            metadata=dict(payload.get("metadata", {})),
        )


@dataclass(frozen=True)
class CapabilityMatch:
    capability: Capability
    score: float
    matched: frozenset[str]
    missing: frozenset[str]


class CapabilityManager:
    """Thread-safe registry and deterministic capability selector."""

    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}
        self._handlers: dict[str, CapabilityHandler] = {}
        self._lock = threading.RLock()

    def register(
        self,
        capability: Capability,
        *,
        handler: CapabilityHandler | None = None,
        replace: bool = False,
    ) -> Capability:
        with self._lock:
            if capability.name in self._capabilities and not replace:
                raise ValueError(
                    f"capability already registered: {capability.name}"
                )

            self._capabilities[capability.name] = capability

            if handler is not None:
                self._handlers[capability.name] = handler
            elif replace:
                self._handlers.pop(capability.name, None)

        return capability

    def unregister(self, name: str) -> bool:
        key = _normalize(name)

        with self._lock:
            existed = key in self._capabilities
            self._capabilities.pop(key, None)
            self._handlers.pop(key, None)
            return existed

    def get(self, name: str) -> Capability | None:
        with self._lock:
            return self._capabilities.get(_normalize(name))

    def list(
        self,
        *,
        enabled_only: bool = False,
    ) -> tuple[Capability, ...]:
        with self._lock:
            capabilities = tuple(self._capabilities.values())

        if enabled_only:
            capabilities = tuple(
                item for item in capabilities if item.enabled
            )

        return tuple(
            sorted(
                capabilities,
                key=lambda item: (-item.priority, item.name),
            )
        )

    def set_enabled(self, name: str, enabled: bool) -> Capability:
        key = _normalize(name)

        with self._lock:
            current = self._capabilities.get(key)
            if current is None:
                raise KeyError(f"unknown capability: {name}")

            replacement = Capability(
                name=current.name,
                description=current.description,
                supports=current.supports,
                priority=current.priority,
                enabled=enabled,
                provider=current.provider,
                metadata=current.metadata,
            )
            self._capabilities[key] = replacement
            return replacement

    def matches(
        self,
        requirements: Iterable[str],
        *,
        provider: str = "",
        include_disabled: bool = False,
        require_all: bool = True,
    ) -> tuple[CapabilityMatch, ...]:
        required = _normalize_tags(requirements)
        provider_key = _normalize(provider)

        if not required:
            return ()

        results: list[CapabilityMatch] = []

        for capability in self.list():
            if not include_disabled and not capability.enabled:
                continue

            if (
                provider_key
                and capability.provider
                and capability.provider != provider_key
            ):
                continue

            matched = required & capability.supports
            missing = required - capability.supports

            if require_all and missing:
                continue

            if not matched:
                continue

            coverage = len(matched) / len(required)
            priority_bonus = max(-100, min(100, capability.priority)) / 1000
            exact_bonus = 0.1 if not missing else 0.0
            provider_bonus = (
                0.05
                if provider_key and capability.provider == provider_key
                else 0.0
            )

            score = round(
                coverage + priority_bonus + exact_bonus + provider_bonus,
                6,
            )

            results.append(
                CapabilityMatch(
                    capability=capability,
                    score=score,
                    matched=matched,
                    missing=missing,
                )
            )

        results.sort(
            key=lambda item: (
                -item.score,
                -item.capability.priority,
                item.capability.name,
            )
        )
        return tuple(results)

    def select(
        self,
        requirements: Iterable[str],
        *,
        provider: str = "",
        require_all: bool = True,
    ) -> CapabilityMatch | None:
        matches = self.matches(
            requirements,
            provider=provider,
            require_all=require_all,
        )
        return matches[0] if matches else None

    def handler(self, name: str) -> CapabilityHandler | None:
        with self._lock:
            return self._handlers.get(_normalize(name))

    def invoke(self, name: str, *args: Any, **kwargs: Any) -> Any:
        capability = self.get(name)

        if capability is None:
            raise KeyError(f"unknown capability: {name}")

        if not capability.enabled:
            raise RuntimeError(f"capability is disabled: {capability.name}")

        handler = self.handler(name)

        if handler is None:
            raise RuntimeError(
                f"capability has no registered handler: {capability.name}"
            )

        return handler(*args, **kwargs)

    def save(self, path: Path) -> Path:
        destination = Path(path).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")

        payload = {
            "version": 1,
            "capabilities": [
                item.to_dict()
                for item in sorted(
                    self._capabilities.values(),
                    key=lambda capability: capability.name,
                )
            ],
        }

        temporary.write_text(
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
        return destination

    @classmethod
    def load(cls, path: Path) -> "CapabilityManager":
        source = Path(path).resolve()
        payload = json.loads(source.read_text(encoding="utf-8"))

        if payload.get("version") != 1:
            raise ValueError("unsupported capability registry version")

        manager = cls()

        for item in payload.get("capabilities", ()):
            manager.register(Capability.from_dict(item))

        return manager


def default_capability_manager() -> CapabilityManager:
    """Return the built-in Sophyane capability catalogue."""
    manager = CapabilityManager()

    defaults = (
        Capability(
            name="browser",
            description="Build and validate browser applications.",
            supports=frozenset(
                {
                    "browser",
                    "html",
                    "css",
                    "javascript",
                    "responsive-ui",
                }
            ),
            priority=90,
        ),
        Capability(
            name="python",
            description="Create and execute Python programs.",
            supports=frozenset(
                {
                    "python",
                    "data-processing",
                    "automation",
                    "testing",
                }
            ),
            priority=80,
        ),
        Capability(
            name="shell",
            description="Execute shell-based project operations.",
            supports=frozenset(
                {
                    "bash",
                    "shell",
                    "build",
                    "filesystem",
                    "testing",
                }
            ),
            priority=75,
        ),
        Capability(
            name="cpp",
            description="Build and test C++ applications.",
            supports=frozenset(
                {
                    "cpp",
                    "cmake",
                    "native-build",
                    "testing",
                }
            ),
            priority=70,
        ),
    )

    for capability in defaults:
        manager.register(capability)

    return manager
