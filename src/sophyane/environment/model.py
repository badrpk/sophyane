"""Core Sophyane Research Environment models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EnvironmentProfile:
    action_depth: int = 1
    event_rate: float = 0.0
    ambiguity: float = 0.0
    noise: float = 0.0
    app_count: int = 1
    temporal_pressure: float = 0.0
    actor_count: int = 1
    hidden_state: float = 0.0

    def normalized_score(self) -> float:
        raw = (
            min(5, max(0, int(self.action_depth))) / 5.0
            + min(10.0, max(0.0, float(self.event_rate))) / 10.0
            + min(1.0, max(0.0, float(self.ambiguity)))
            + min(1.0, max(0.0, float(self.noise)))
            + min(8, max(0, int(self.app_count))) / 8.0
            + min(1.0, max(0.0, float(self.temporal_pressure)))
            + min(8, max(0, int(self.actor_count))) / 8.0
            + min(1.0, max(0.0, float(self.hidden_state)))
        )

        return max(
            0.0,
            min(
                1.0,
                raw / 8.0,
            ),
        )


@dataclass(frozen=True)
class EnvironmentEvent:
    event_id: str
    at: float
    kind: str
    payload: dict[str, Any] = field(
        default_factory=dict
    )
    hidden: bool = False
    source: str = "environment"


@dataclass(frozen=True)
class EnvironmentAction:
    actor: str
    action: str
    payload: dict[str, Any] = field(
        default_factory=dict
    )
    at: float | None = None


@dataclass(frozen=True)
class TraceEntry:
    sequence: int
    clock: float
    kind: str
    actor: str
    payload: dict[str, Any]
    state_digest: str


@dataclass
class Scenario:
    scenario_id: str
    objective: str
    initial_state: dict[str, Any] = field(
        default_factory=dict
    )
    events: tuple[EnvironmentEvent, ...] = ()
    profile: EnvironmentProfile = field(
        default_factory=EnvironmentProfile
    )
    metadata: dict[str, Any] = field(
        default_factory=dict
    )
    seed: int = 0
    max_clock: float = 300.0
    max_steps: int = 32


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    score: float
    verifier: str
    evidence: tuple[str, ...] = ()
    details: dict[str, Any] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    success: bool
    score: float
    final_clock: float
    steps: int
    verification: VerificationResult
    trace_path: str = ""
    stop_reason: str = ""
