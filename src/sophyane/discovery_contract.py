"""Typed contracts for the Sophyane Discovery Engine."""
from __future__ import annotations

import hashlib
import time

from dataclasses import asdict, dataclass, field
from typing import Any


def stable_id(
    prefix: str,
    *parts: object,
) -> str:
    material = "\0".join(
        str(item or "")
        for item in parts
    )

    digest = hashlib.sha256(
        material.encode(
            "utf-8"
        )
    ).hexdigest()[:20]

    return (
        f"{prefix}-"
        f"{digest}"
    )


@dataclass(frozen=True)
class KnowledgeRecord:
    source: str
    kind: str
    content: str
    score: float = 0.0
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Hypothesis:
    hypothesis_id: str
    statement: str
    rationale: str = ""
    predictions: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    source: str = "reasoner"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    hypothesis_id: str
    description: str
    mechanism: str = ""
    expected_value: str = ""
    novelty_score: float = 0.0
    novelty_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExperimentPlan:
    experiment_id: str
    candidate_id: str
    experiment_type: str
    procedure: tuple[str, ...]
    success_criteria: tuple[str, ...]
    measurements: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
    safe_for_autonomous_execution: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Observation:
    experiment_id: str
    executed: bool
    ok: bool
    output: str
    measurements: dict[str, Any] = field(
        default_factory=dict
    )
    evidence: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationResult:
    validator: str
    passed: bool
    score: float
    summary: str
    evidence: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DiscoveryCandidateResult:
    candidate: Candidate
    experiment: ExperimentPlan
    observation: Observation
    validations: tuple[ValidationResult, ...]
    reproduced: bool
    final_novelty_score: float
    accepted: bool
    rejection_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": (
                self.candidate.to_dict()
            ),
            "experiment": (
                self.experiment.to_dict()
            ),
            "observation": (
                self.observation.to_dict()
            ),
            "validations": [
                item.to_dict()
                for item in self.validations
            ],
            "reproduced": self.reproduced,
            "final_novelty_score": (
                self.final_novelty_score
            ),
            "accepted": self.accepted,
            "rejection_reason": (
                self.rejection_reason
            ),
        }


@dataclass(frozen=True)
class DiscoveryEpisode:
    episode_id: str
    objective: str
    knowledge: tuple[KnowledgeRecord, ...]
    hypotheses: tuple[Hypothesis, ...]
    results: tuple[
        DiscoveryCandidateResult,
        ...
    ]
    started_at: float
    finished_at: float
    accepted_candidates: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "objective": self.objective,
            "knowledge": [
                item.to_dict()
                for item in self.knowledge
            ],
            "hypotheses": [
                item.to_dict()
                for item in self.hypotheses
            ],
            "results": [
                item.to_dict()
                for item in self.results
            ],
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_seconds": max(
                0.0,
                self.finished_at
                - self.started_at,
            ),
            "accepted_candidates": list(
                self.accepted_candidates
            ),
        }


def new_episode_id(
    objective: str,
) -> str:
    return stable_id(
        "discovery",
        objective,
        time.time_ns(),
    )


__all__ = [
    "Candidate",
    "DiscoveryCandidateResult",
    "DiscoveryEpisode",
    "ExperimentPlan",
    "Hypothesis",
    "KnowledgeRecord",
    "Observation",
    "ValidationResult",
    "new_episode_id",
    "stable_id",
]
