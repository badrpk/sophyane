"""Cross-capability information-flow policy for Sophyane.

This module is deliberately pure policy/data logic.

It has no:
- shell execution authority;
- network authority;
- provider authority;
- filesystem mutation authority;
- Git promotion authority.

Security principle
------------------
A sequence of individually permitted capabilities is NOT automatically
a permitted composite capability.

Sensitivity and provenance travel with information across transformations.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import IntEnum
import hashlib
import json
from typing import Any, Iterable


class Sensitivity(IntEnum):
    PUBLIC = 0
    INTERNAL = 10
    USER_PRIVATE = 20
    AUTH_SECRET = 30
    SYSTEM_SECRET = 40


@dataclass(frozen=True)
class ProvenanceEdge:
    source_id: str
    operation: str
    capability: str
    detail: str = ""


@dataclass(frozen=True)
class FlowLabel:
    sensitivity: Sensitivity = Sensitivity.PUBLIC
    categories: frozenset[str] = field(
        default_factory=frozenset
    )
    provenance: tuple[ProvenanceEdge, ...] = ()
    origin_ids: frozenset[str] = field(
        default_factory=frozenset
    )
    declassified: bool = False

    def derive(
        self,
        *,
        capability: str,
        operation: str,
        source_id: str = "",
        detail: str = "",
        categories: Iterable[str] = (),
        sensitivity: Sensitivity | None = None,
    ) -> "FlowLabel":
        next_sensitivity = max(
            self.sensitivity,
            (
                sensitivity
                if sensitivity is not None
                else self.sensitivity
            ),
        )

        origins = set(
            self.origin_ids
        )

        if source_id:
            origins.add(
                source_id
            )

        edge = ProvenanceEdge(
            source_id=source_id,
            operation=operation,
            capability=capability,
            detail=detail,
        )

        return FlowLabel(
            sensitivity=next_sensitivity,
            categories=frozenset(
                set(self.categories)
                | {
                    str(item)
                    for item in categories
                    if str(item)
                }
            ),
            provenance=(
                self.provenance
                + (
                    edge,
                )
            ),
            origin_ids=frozenset(
                origins
            ),
            declassified=self.declassified,
        )


@dataclass(frozen=True)
class LabeledValue:
    value: Any
    label: FlowLabel
    value_id: str

    @classmethod
    def create(
        cls,
        value: Any,
        *,
        sensitivity: Sensitivity = Sensitivity.PUBLIC,
        categories: Iterable[str] = (),
        origin: str = "",
    ) -> "LabeledValue":
        canonical = json.dumps(
            value,
            sort_keys=True,
            default=str,
            separators=(
                ",",
                ":",
            ),
        )

        value_id = hashlib.sha256(
            canonical.encode(
                "utf-8"
            )
        ).hexdigest()[:24]

        origins = (
            frozenset(
                {
                    origin
                }
            )
            if origin
            else frozenset()
        )

        return cls(
            value=value,
            label=FlowLabel(
                sensitivity=sensitivity,
                categories=frozenset(
                    str(item)
                    for item in categories
                    if str(item)
                ),
                origin_ids=origins,
            ),
            value_id=value_id,
        )

    def transformed(
        self,
        value: Any,
        *,
        capability: str,
        operation: str,
        sensitivity: Sensitivity | None = None,
        categories: Iterable[str] = (),
        detail: str = "",
    ) -> "LabeledValue":
        label = self.label.derive(
            capability=capability,
            operation=operation,
            source_id=self.value_id,
            detail=detail,
            categories=categories,
            sensitivity=sensitivity,
        )

        canonical = json.dumps(
            value,
            sort_keys=True,
            default=str,
            separators=(
                ",",
                ":",
            ),
        )

        new_id = hashlib.sha256(
            canonical.encode(
                "utf-8"
            )
        ).hexdigest()[:24]

        return LabeledValue(
            value=value,
            label=label,
            value_id=new_id,
        )


@dataclass(frozen=True)
class CapabilityDescriptor:
    capability_id: str
    reads: frozenset[str] = field(
        default_factory=frozenset
    )
    writes: frozenset[str] = field(
        default_factory=frozenset
    )
    maximum_input_sensitivity: Sensitivity = (
        Sensitivity.PUBLIC
    )
    maximum_output_sensitivity: Sensitivity = (
        Sensitivity.PUBLIC
    )
    external_sink: bool = False
    persistent_sink: bool = False
    executable_sink: bool = False
    side_effects: frozenset[str] = field(
        default_factory=frozenset
    )
    required_verifiers: frozenset[str] = field(
        default_factory=frozenset
    )


@dataclass(frozen=True)
class FlowDecision:
    allowed: bool
    reason: str
    required_verifiers: frozenset[str] = field(
        default_factory=frozenset
    )


FORBIDDEN_EXTERNAL_CATEGORIES = frozenset(
    {
        "credential",
        "authentication",
        "private_key",
        "session_token",
        "cookie",
        "user_secret",
        "system_secret",
    }
)


def evaluate_capability_input(
    descriptor: CapabilityDescriptor,
    value: LabeledValue,
) -> FlowDecision:
    if (
        value.label.sensitivity
        > descriptor.maximum_input_sensitivity
    ):
        return FlowDecision(
            allowed=False,
            reason=(
                "input sensitivity exceeds capability allowance"
            ),
        )

    if descriptor.external_sink:
        forbidden = (
            value.label.categories
            & FORBIDDEN_EXTERNAL_CATEGORIES
        )

        if forbidden:
            return FlowDecision(
                allowed=False,
                reason=(
                    "sensitive category cannot flow to external sink: "
                    + ",".join(
                        sorted(
                            forbidden
                        )
                    )
                ),
            )

        if (
            value.label.sensitivity
            >= Sensitivity.AUTH_SECRET
        ):
            return FlowDecision(
                allowed=False,
                reason=(
                    "secret material cannot flow to external sink"
                ),
            )

    return FlowDecision(
        allowed=True,
        reason="allowed",
        required_verifiers=(
            descriptor.required_verifiers
        ),
    )


def combine_labels(
    *labels: FlowLabel,
) -> FlowLabel:
    if not labels:
        return FlowLabel()

    sensitivity = max(
        item.sensitivity
        for item in labels
    )

    categories: set[str] = set()
    provenance: list[
        ProvenanceEdge
    ] = []
    origins: set[str] = set()

    for item in labels:
        categories.update(
            item.categories
        )

        provenance.extend(
            item.provenance
        )

        origins.update(
            item.origin_ids
        )

    return FlowLabel(
        sensitivity=sensitivity,
        categories=frozenset(
            categories
        ),
        provenance=tuple(
            provenance
        ),
        origin_ids=frozenset(
            origins
        ),
        declassified=False,
    )


def derived_from_sensitive_origin(
    label: FlowLabel,
) -> bool:
    return bool(
        label.sensitivity
        >= Sensitivity.USER_PRIVATE
        or label.categories
        & FORBIDDEN_EXTERNAL_CATEGORIES
    )


def label_summary(
    label: FlowLabel,
) -> dict[str, Any]:
    return {
        "sensitivity":
            label.sensitivity.name,
        "categories":
            sorted(
                label.categories
            ),
        "origin_ids":
            sorted(
                label.origin_ids
            ),
        "provenance_depth":
            len(
                label.provenance
            ),
        "declassified":
            label.declassified,
    }


__all__ = [
    "CapabilityDescriptor",
    "FlowDecision",
    "FlowLabel",
    "LabeledValue",
    "ProvenanceEdge",
    "Sensitivity",
    "combine_labels",
    "derived_from_sensitive_origin",
    "evaluate_capability_input",
    "label_summary",
]
