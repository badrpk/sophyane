"""Evidence-gated primitives for recursive Sophyane kernel improvement.

This module does not modify the running kernel.  It records failures, chooses a
bounded recovery strategy, and represents improvement proposals that must pass
explicit gates before deployment.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


class FailureKind(str, Enum):
    PROVIDER_TIMEOUT = "provider_timeout"
    CONTEXT_OVERFLOW = "context_overflow"
    OUTPUT_TRUNCATION = "output_truncation"
    MALFORMED_PROTOCOL = "malformed_protocol"
    INCOMPLETE_ARTIFACT = "incomplete_artifact"
    SYNTAX_ERROR = "syntax_error"
    BUILD_FAILURE = "build_failure"
    TEST_FAILURE = "test_failure"
    RUNTIME_FAILURE = "runtime_failure"
    BLANK_UI = "blank_ui"
    MISSING_ASSET = "missing_asset"
    REQUIREMENT_MISSING = "requirement_missing"
    RESOURCE_LIMIT = "resource_limit"
    UNSAFE_ACTION = "unsafe_action"
    UNKNOWN = "unknown"


class RecoveryStrategy(str, Enum):
    REDUCE_CONTEXT = "reduce_context"
    DECOMPOSE_TASK = "decompose_task"
    CONTINUE_ARTIFACT = "continue_artifact"
    SALVAGE_FRAGMENTS = "salvage_fragments"
    NORMALIZE_PROTOCOL = "normalize_protocol"
    TARGETED_REPAIR = "targeted_repair"
    INSTALL_OR_SELECT_TOOLCHAIN = "install_or_select_toolchain"
    RUN_DETERMINISTIC_CHECKS = "run_deterministic_checks"
    RESTORE_LAST_GOOD = "restore_last_good"
    ESCALATE_WITH_PERMISSION = "escalate_with_permission"
    STOP_SAFELY = "stop_safely"


@dataclass(frozen=True)
class HardwareEnvelope:
    os_name: str
    architecture: str
    ram_mb: int | None = None
    free_disk_mb: int | None = None
    cpu_count: int | None = None
    model_context_tokens: int | None = None
    model_output_tokens: int | None = None
    network_available: bool | None = None
    tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class FailureRecord:
    task_id: str
    kind: FailureKind
    summary: str
    evidence: tuple[str, ...] = ()
    artifact_paths: tuple[str, ...] = ()
    attempt: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ImprovementProposal:
    proposal_id: str
    failure: FailureRecord
    hypothesis: str
    changed_paths: tuple[str, ...]
    required_checks: tuple[str, ...]
    rollback_ref: str
    branch_name: str


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    evidence: str


class RecoveryPolicy:
    """Choose a bounded next action from classified evidence."""

    _DEFAULTS: dict[FailureKind, tuple[RecoveryStrategy, ...]] = {
        FailureKind.CONTEXT_OVERFLOW: (
            RecoveryStrategy.REDUCE_CONTEXT,
            RecoveryStrategy.DECOMPOSE_TASK,
        ),
        FailureKind.OUTPUT_TRUNCATION: (
            RecoveryStrategy.SALVAGE_FRAGMENTS,
            RecoveryStrategy.CONTINUE_ARTIFACT,
            RecoveryStrategy.DECOMPOSE_TASK,
        ),
        FailureKind.MALFORMED_PROTOCOL: (
            RecoveryStrategy.SALVAGE_FRAGMENTS,
            RecoveryStrategy.NORMALIZE_PROTOCOL,
        ),
        FailureKind.INCOMPLETE_ARTIFACT: (
            RecoveryStrategy.SALVAGE_FRAGMENTS,
            RecoveryStrategy.TARGETED_REPAIR,
            RecoveryStrategy.DECOMPOSE_TASK,
        ),
        FailureKind.SYNTAX_ERROR: (
            RecoveryStrategy.RUN_DETERMINISTIC_CHECKS,
            RecoveryStrategy.TARGETED_REPAIR,
        ),
        FailureKind.BUILD_FAILURE: (
            RecoveryStrategy.RUN_DETERMINISTIC_CHECKS,
            RecoveryStrategy.TARGETED_REPAIR,
        ),
        FailureKind.TEST_FAILURE: (
            RecoveryStrategy.TARGETED_REPAIR,
            RecoveryStrategy.RESTORE_LAST_GOOD,
        ),
        FailureKind.MISSING_ASSET: (
            RecoveryStrategy.TARGETED_REPAIR,
            RecoveryStrategy.DECOMPOSE_TASK,
        ),
        FailureKind.RESOURCE_LIMIT: (
            RecoveryStrategy.REDUCE_CONTEXT,
            RecoveryStrategy.DECOMPOSE_TASK,
        ),
        FailureKind.UNSAFE_ACTION: (RecoveryStrategy.STOP_SAFELY,),
    }

    def choose(
        self,
        failure: FailureRecord,
        hardware: HardwareEnvelope,
        *,
        max_attempts: int = 3,
    ) -> tuple[RecoveryStrategy, ...]:
        if failure.attempt >= max_attempts:
            return (RecoveryStrategy.STOP_SAFELY,)
        strategies = self._DEFAULTS.get(
            failure.kind,
            (RecoveryStrategy.TARGETED_REPAIR, RecoveryStrategy.STOP_SAFELY),
        )
        if hardware.model_context_tokens and hardware.model_context_tokens <= 2048:
            if RecoveryStrategy.DECOMPOSE_TASK not in strategies:
                strategies = strategies + (RecoveryStrategy.DECOMPOSE_TASK,)
        return strategies


class ImprovementGate:
    """Evaluate an isolated proposal; deployment remains a separate action."""

    REQUIRED_GATE_NAMES = (
        "static_checks",
        "focused_regression",
        "available_test_suite",
        "benchmark_non_regression",
        "safety_boundaries",
        "rollback_ready",
        "approval",
    )

    @classmethod
    def approved(cls, results: Iterable[GateResult]) -> bool:
        by_name = {result.name: result for result in results}
        return all(
            name in by_name and by_name[name].passed
            for name in cls.REQUIRED_GATE_NAMES
        )

    @classmethod
    def missing_or_failed(cls, results: Iterable[GateResult]) -> list[str]:
        by_name = {result.name: result for result in results}
        return [
            name
            for name in cls.REQUIRED_GATE_NAMES
            if name not in by_name or not by_name[name].passed
        ]


def safe_artifact_paths(workspace: Path, paths: Iterable[str]) -> tuple[Path, ...]:
    """Resolve evidence artifacts without allowing workspace escape."""
    root = workspace.resolve()
    resolved: list[Path] = []
    for value in paths:
        candidate = (root / value).resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError(f"Artifact path escapes workspace: {value}")
        resolved.append(candidate)
    return tuple(resolved)
