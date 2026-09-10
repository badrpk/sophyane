"""Typed benchmark contract for product-completeness engineering.

Benchmarks expand an underspecified product request but never override
the user's immutable objective.

This module contains data contracts only. It performs no network I/O,
does not certify products, and does not trust model claims as evidence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Iterable

SCHEMA = 1

BENCHMARK_ROLES = {
    "marketplace",
    "service_brokerage",
    "adoption",
    "commerce",
    "content",
    "community",
    "trust",
    "discovery",
    "provider_platform",
    "consumer_platform",
}

IMPLEMENTATION_KINDS = {
    "static_content",
    "interactive_local_workflow",
    "live_backend",
    "external_integration",
}

EVIDENCE_KINDS = {
    "dom",
    "render",
    "interaction",
    "persistence",
    "backend",
    "external",
}


def _norm(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _stable_hash(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")

    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class BenchmarkReference:
    benchmark_id: str
    name: str
    url: str
    role: str
    domain: str = ""
    rationale: str = ""
    capabilities: tuple[str, ...] = ()

    def __post_init__(self):
        role = _norm(self.role)

        if role not in BENCHMARK_ROLES:
            raise ValueError(
                f"unsupported benchmark role: {self.role}"
            )

        if not str(self.benchmark_id or "").strip():
            raise ValueError("benchmark_id required")

        if not str(self.name or "").strip():
            raise ValueError("benchmark name required")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkCapability:
    capability_id: str
    title: str
    description: str

    source_benchmarks: tuple[str, ...] = ()

    benchmark_required: bool = True
    original_request_required: bool = False
    applicable: bool = True

    implementation: str = "interactive_local_workflow"
    backend_required_for_live_use: bool = False

    verification_steps: tuple[str, ...] = ()
    required_evidence: tuple[str, ...] = ("interaction",)

    def __post_init__(self):
        if not str(self.capability_id or "").strip():
            raise ValueError("capability_id required")

        if self.implementation not in IMPLEMENTATION_KINDS:
            raise ValueError(
                "unsupported implementation kind: "
                + self.implementation
            )

        unknown = set(self.required_evidence) - EVIDENCE_KINDS

        if unknown:
            raise ValueError(
                "unsupported evidence kind(s): "
                + ", ".join(sorted(unknown))
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkContract:
    schema: int
    objective: str
    objective_hash: str

    benchmarks: tuple[BenchmarkReference, ...]
    capabilities: tuple[BenchmarkCapability, ...]

    contract_hash: str = ""

    def __post_init__(self):
        objective = str(self.objective or "").strip()

        if not objective:
            raise ValueError("objective required")

        if len(self.benchmarks) > 3:
            raise ValueError(
                "at most three primary benchmarks are allowed"
            )

        ids = [
            item.benchmark_id
            for item in self.benchmarks
        ]

        if len(ids) != len(set(ids)):
            raise ValueError(
                "duplicate benchmark_id"
            )

        capability_ids = [
            item.capability_id
            for item in self.capabilities
        ]

        if len(capability_ids) != len(set(capability_ids)):
            raise ValueError(
                "duplicate capability_id"
            )

    def payload(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "objective": self.objective,
            "objective_hash": self.objective_hash,
            "benchmarks": [
                item.to_dict()
                for item in self.benchmarks
            ],
            "capabilities": [
                item.to_dict()
                for item in self.capabilities
            ],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.payload(),
            "contract_hash": (
                self.contract_hash
                or _stable_hash(self.payload())
            ),
        }


def objective_digest(objective: str) -> str:
    normalized = " ".join(
        str(objective or "").strip().split()
    )

    return hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()


def build_contract(
    *,
    objective: str,
    benchmarks: Iterable[BenchmarkReference],
    capabilities: Iterable[BenchmarkCapability],
) -> BenchmarkContract:
    objective_text = " ".join(
        str(objective or "").strip().split()
    )

    contract = BenchmarkContract(
        schema=SCHEMA,
        objective=objective_text,
        objective_hash=objective_digest(
            objective_text
        ),
        benchmarks=tuple(benchmarks),
        capabilities=tuple(capabilities),
    )

    return replace(
        contract,
        contract_hash=_stable_hash(
            contract.payload()
        ),
    )


def validate_original_request_authority(
    contract: BenchmarkContract,
) -> tuple[bool, tuple[str, ...]]:
    """
    Benchmark-derived capabilities may expand scope, but an explicitly
    required user capability may never be marked inapplicable or optional.
    """
    violations: list[str] = []

    for capability in contract.capabilities:
        if not capability.original_request_required:
            continue

        if not capability.applicable:
            violations.append(
                capability.capability_id
                + ":original_request_marked_inapplicable"
            )

        if not capability.benchmark_required:
            violations.append(
                capability.capability_id
                + ":original_request_marked_optional"
            )

    return (
        not violations,
        tuple(violations),
    )


__all__ = [
    "BENCHMARK_ROLES",
    "EVIDENCE_KINDS",
    "IMPLEMENTATION_KINDS",
    "BenchmarkCapability",
    "BenchmarkContract",
    "BenchmarkReference",
    "build_contract",
    "objective_digest",
    "validate_original_request_authority",
]
