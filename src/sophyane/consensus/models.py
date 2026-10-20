"""Immutable records exchanged by the consensus validation layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ValidatedVote:
    worker_id: str
    decision: dict[str, Any]
    digest: str
    git_head: str
    failure_boundary: None = None


@dataclass(frozen=True)
class InvalidVote:
    worker_id: str | None
    digest: None
    decision: None
    git_head: str | None
    failure_boundary: str
    error: str


@dataclass(frozen=True)
class ConsensusDecision:
    round_id: str
    status: str
    decision: dict[str, Any] | None
    quorum: int
    elapsed_ms: float
    votes: tuple[ValidatedVote | InvalidVote, ...]
    isolated_workers: tuple[str, ...]

