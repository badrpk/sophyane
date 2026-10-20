"""Immutable public data contracts for mutation planning and results."""

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping


@dataclass(frozen=True)
class MutationIntent:
    summary: str
    source_root: Path
    allowed_paths: tuple[str, ...]
    invariants: tuple[str, ...] = ()


@dataclass(frozen=True)
class MutationProposal:
    replacements: Mapping[str, str]
    planner_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "replacements", MappingProxyType(dict(self.replacements)))


@dataclass(frozen=True)
class MutationResult:
    status: Literal["accepted", "reversed"]
    transaction_id: str
    lab_path: Path
    baseline_hash: str
    candidate_hash: str
    semantic_diff_hash: str
    reversal_patch: str
    failure_boundary: str | None
    checks: tuple[str, ...]
