"""Whole-chain execution admission.

NIFDU or any model may recommend a capability sequence.
This guard is the authority deciding whether the declared sequence may
carry a labeled value.

It performs no actual side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sophyane.capability_flow_graph import (
    CapabilityGraph,
    ChainValidation,
)
from sophyane.capability_flow_policy import (
    LabeledValue,
)
from sophyane.capability_leases import (
    CapabilityLeaseManager,
)


@dataclass(frozen=True)
class ChainRequest:
    capabilities: tuple[str, ...]
    scope: str
    verifier_evidence: frozenset[str] = field(
        default_factory=frozenset
    )


@dataclass(frozen=True)
class ChainAdmission:
    allowed: bool
    reason: str
    missing_verifiers: frozenset[str] = field(
        default_factory=frozenset
    )


class CapabilityChainGuard:
    def __init__(
        self,
        *,
        graph: CapabilityGraph,
        leases:
            CapabilityLeaseManager
            | None = None,
    ) -> None:
        self.graph = graph
        self.leases = (
            leases
            or CapabilityLeaseManager()
        )

    def evaluate(
        self,
        *,
        request: ChainRequest,
        value: LabeledValue,
    ) -> ChainAdmission:
        validation = (
            self.graph.validate_chain(
                request.capabilities,
                value,
            )
        )

        if not validation.allowed:
            return ChainAdmission(
                allowed=False,
                reason=validation.reason,
            )

        missing = (
            validation.required_verifiers
            - request.verifier_evidence
        )

        if missing:
            return ChainAdmission(
                allowed=False,
                reason=(
                    "missing verifier evidence"
                ),
                missing_verifiers=(
                    frozenset(
                        missing
                    )
                ),
            )

        return ChainAdmission(
            allowed=True,
            reason="allowed",
        )

    def issue_leases(
        self,
        *,
        request: ChainRequest,
        value: LabeledValue,
        ttl_seconds: float = 30.0,
    ) -> tuple[str, ...]:
        admission = self.evaluate(
            request=request,
            value=value,
        )

        if not admission.allowed:
            return ()

        leases = []

        for capability in (
            request.capabilities
        ):
            lease = self.leases.issue(
                capability=capability,
                scope=request.scope,
                ttl_seconds=ttl_seconds,
                max_uses=1,
            )

            leases.append(
                lease.lease_id
            )

        return tuple(
            leases
        )


__all__ = [
    "CapabilityChainGuard",
    "ChainAdmission",
    "ChainRequest",
]
