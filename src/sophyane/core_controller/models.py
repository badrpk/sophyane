"""Typed, serializable contracts for the Sophyane core controller."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


MAX_TEXT = 10_000


class ModeName(str, Enum):
    RACE = "race"
    SLI_GRAPH = "sli_graph"
    LOCAL_LLM = "local_llm"
    EXTERNAL_LLM = "external_llm"
    LEARNING = "learning"
    HUMAN_CONVERSATION = "human_conversation"


class FailureBoundary(str, Enum):
    REQUEST_INVALID = "request_invalid"
    MODE_UNAVAILABLE = "mode_unavailable"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    EXECUTION_DENIED = "execution_denied"
    WORKSPACE_CONTAINMENT = "workspace_containment"
    VERIFICATION_FAILED = "verification_failed"
    PROMOTION_DENIED = "promotion_denied"
    STATE_UNAVAILABLE = "state_unavailable"
    CONTROLLER_INTERNAL = "controller_internal"


def _bounded_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be text")
    if len(value) > MAX_TEXT:
        raise ValueError(f"{field_name} exceeds {MAX_TEXT} characters")
    return value


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


class _Serializable:
    def to_dict(self) -> dict[str, Any]:
        values = {
            key: _json_value(value)
            for key, value in self.__dict__.items()
        }
        return {key: values[key] for key in sorted(values)}


@dataclass(frozen=True)
class ControllerRequest(_Serializable):
    text: str
    caller_id: str = ""
    requested_mode: ModeName | None = None
    session_id: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _bounded_text(self.text, "text")
        _bounded_text(self.caller_id, "caller_id")
        _bounded_text(self.session_id, "session_id")


@dataclass(frozen=True)
class ControllerContext(_Serializable):
    available_modes: tuple[ModeName, ...] = ()
    session_mode: ModeName | None = None
    state: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModePlan(_Serializable):
    trace_id: str
    mode: ModeName
    provider_intent: str = ""
    requested_capabilities: tuple[str, ...] = ()
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _bounded_text(self.trace_id, "trace_id")
        _bounded_text(self.provider_intent, "provider_intent")


@dataclass(frozen=True)
class ProviderDecision(_Serializable):
    trace_id: str
    provider: str
    fallback_chain: tuple[str, ...] = ()
    ready: bool = False
    reason: str = ""

    def __post_init__(self) -> None:
        _bounded_text(self.trace_id, "trace_id")
        _bounded_text(self.provider, "provider")
        _bounded_text(self.reason, "reason")


@dataclass(frozen=True)
class ExecutionResult(_Serializable):
    approved: bool
    completed: bool
    output: Any = None
    verification_status: str = "not_run"
    failure_boundary: FailureBoundary | None = None
    reason: str = ""
    promotion_approved: bool = False

    def __post_init__(self) -> None:
        _bounded_text(self.verification_status, "verification_status")
        _bounded_text(self.reason, "reason")


@dataclass(frozen=True)
class ModeResult(_Serializable):
    trace_id: str
    mode: ModeName
    disposition: str
    output: Any = None
    verification_status: str = "not_run"
    failure_boundary: FailureBoundary | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        _bounded_text(self.trace_id, "trace_id")
        _bounded_text(self.disposition, "disposition")
        _bounded_text(self.verification_status, "verification_status")
        _bounded_text(self.reason, "reason")

    @classmethod
    def failure(
        cls,
        *,
        trace_id: str,
        mode: ModeName,
        boundary: FailureBoundary,
        reason: str,
    ) -> "ModeResult":
        return cls(
            trace_id=trace_id,
            mode=mode,
            disposition="failed",
            failure_boundary=boundary,
            reason=reason,
        )


@dataclass(frozen=True)
class AuditEvent(_Serializable):
    trace_id: str
    event_type: str
    mode: ModeName | None = None
    disposition: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _bounded_text(self.trace_id, "trace_id")
        _bounded_text(self.event_type, "event_type")
        _bounded_text(self.disposition, "disposition")
