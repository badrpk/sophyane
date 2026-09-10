"""Deterministic benchmark capability coverage.

A capability is verified only when all required evidence types exist
and the workflow itself passed. Model prose is not evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from sophyane.benchmark_contract import (
    BenchmarkCapability,
    BenchmarkContract,
)


@dataclass(frozen=True)
class CapabilityEvidence:
    capability_id: str

    implemented: bool
    workflow_passed: bool

    evidence: tuple[str, ...] = ()
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapabilityResult:
    capability_id: str
    applicable: bool
    implemented: bool
    verified: bool
    missing_evidence: tuple[str, ...]
    workflow_passed: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkCoverage:
    applicable: int
    implemented: int
    verified: int

    workflow_total: int
    workflow_passed: int

    coverage: float
    workflow_coverage: float

    missing_capabilities: tuple[str, ...]
    unverified_capabilities: tuple[str, ...]

    results: tuple[CapabilityResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _evaluate(
    capability: BenchmarkCapability,
    evidence: CapabilityEvidence | None,
) -> CapabilityResult:
    if not capability.applicable:
        return CapabilityResult(
            capability_id=capability.capability_id,
            applicable=False,
            implemented=False,
            verified=False,
            missing_evidence=(),
            workflow_passed=False,
        )

    if evidence is None:
        return CapabilityResult(
            capability_id=capability.capability_id,
            applicable=True,
            implemented=False,
            verified=False,
            missing_evidence=tuple(
                capability.required_evidence
            ),
            workflow_passed=False,
        )

    present = set(evidence.evidence)

    missing = tuple(
        required
        for required in capability.required_evidence
        if required not in present
    )

    verified = (
        evidence.implemented
        and evidence.workflow_passed
        and not missing
    )

    return CapabilityResult(
        capability_id=capability.capability_id,
        applicable=True,
        implemented=bool(
            evidence.implemented
        ),
        verified=verified,
        missing_evidence=missing,
        workflow_passed=bool(
            evidence.workflow_passed
        ),
    )


def evaluate_coverage(
    contract: BenchmarkContract,
    evidence: Iterable[CapabilityEvidence],
) -> BenchmarkCoverage:
    evidence_by_id = {
        item.capability_id: item
        for item in evidence
    }

    results = tuple(
        _evaluate(
            capability,
            evidence_by_id.get(
                capability.capability_id
            ),
        )
        for capability in contract.capabilities
    )

    applicable_rows = [
        item
        for item in results
        if item.applicable
    ]

    applicable = len(applicable_rows)

    implemented = sum(
        1
        for item in applicable_rows
        if item.implemented
    )

    verified = sum(
        1
        for item in applicable_rows
        if item.verified
    )

    workflow_total = applicable

    workflow_passed = sum(
        1
        for item in applicable_rows
        if item.workflow_passed
    )

    coverage = (
        1.0
        if applicable == 0
        else verified / applicable
    )

    workflow_coverage = (
        1.0
        if workflow_total == 0
        else workflow_passed / workflow_total
    )

    missing = tuple(
        item.capability_id
        for item in applicable_rows
        if not item.implemented
    )

    unverified = tuple(
        item.capability_id
        for item in applicable_rows
        if item.implemented
        and not item.verified
    )

    return BenchmarkCoverage(
        applicable=applicable,
        implemented=implemented,
        verified=verified,
        workflow_total=workflow_total,
        workflow_passed=workflow_passed,
        coverage=coverage,
        workflow_coverage=workflow_coverage,
        missing_capabilities=missing,
        unverified_capabilities=unverified,
        results=results,
    )


def benchmark_gate_passes(
    coverage: BenchmarkCoverage,
) -> bool:
    return (
        coverage.coverage == 1.0
        and coverage.workflow_coverage == 1.0
        and not coverage.missing_capabilities
        and not coverage.unverified_capabilities
    )


__all__ = [
    "BenchmarkCoverage",
    "CapabilityEvidence",
    "CapabilityResult",
    "benchmark_gate_passes",
    "evaluate_coverage",
]
