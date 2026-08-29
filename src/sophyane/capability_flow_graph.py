"""Whole-chain capability graph validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from sophyane.capability_flow_policy import (
    CapabilityDescriptor,
    FlowDecision,
    LabeledValue,
    Sensitivity,
    evaluate_capability_input,
)


@dataclass(frozen=True)
class CapabilityNode:
    node_id: str
    descriptor: CapabilityDescriptor


@dataclass(frozen=True)
class CapabilityEdge:
    source: str
    target: str
    channel: str


@dataclass(frozen=True)
class ChainValidation:
    allowed: bool
    reason: str
    path: tuple[str, ...]
    required_verifiers: frozenset[str] = field(
        default_factory=frozenset
    )


class CapabilityGraph:
    def __init__(
        self,
    ) -> None:
        self._nodes: dict[
            str,
            CapabilityNode,
        ] = {}

        self._edges: list[
            CapabilityEdge
        ] = []

    def register(
        self,
        descriptor:
            CapabilityDescriptor,
    ) -> None:
        self._nodes[
            descriptor.capability_id
        ] = CapabilityNode(
            node_id=(
                descriptor.capability_id
            ),
            descriptor=descriptor,
        )

    def connect(
        self,
        source: str,
        target: str,
        *,
        channel: str = "data",
    ) -> None:
        if source not in self._nodes:
            raise KeyError(
                source
            )

        if target not in self._nodes:
            raise KeyError(
                target
            )

        self._edges.append(
            CapabilityEdge(
                source=source,
                target=target,
                channel=channel,
            )
        )

    def descriptor(
        self,
        capability_id: str,
    ) -> CapabilityDescriptor:
        return self._nodes[
            capability_id
        ].descriptor

    def validate_chain(
        self,
        path: Iterable[str],
        value: LabeledValue,
    ) -> ChainValidation:
        ordered = tuple(
            path
        )

        if not ordered:
            return ChainValidation(
                allowed=False,
                reason="empty capability chain",
                path=(),
            )

        for capability_id in ordered:
            if capability_id not in self._nodes:
                return ChainValidation(
                    allowed=False,
                    reason=(
                        "unknown capability: "
                        + capability_id
                    ),
                    path=ordered,
                )

        required: set[str] = set()

        for index, capability_id in enumerate(
            ordered
        ):
            descriptor = self.descriptor(
                capability_id
            )

            decision = (
                evaluate_capability_input(
                    descriptor,
                    value,
                )
            )

            if not decision.allowed:
                return ChainValidation(
                    allowed=False,
                    reason=(
                        capability_id
                        + ": "
                        + decision.reason
                    ),
                    path=ordered,
                )

            required.update(
                decision.required_verifiers
            )

            if index:
                previous = (
                    ordered[
                        index - 1
                    ]
                )

                if not any(
                    edge.source
                    == previous
                    and edge.target
                    == capability_id
                    for edge
                    in self._edges
                ):
                    return ChainValidation(
                        allowed=False,
                        reason=(
                            "undeclared capability transition: "
                            + previous
                            + " -> "
                            + capability_id
                        ),
                        path=ordered,
                    )

            #
            # High-sensitivity material may not be transformed through an
            # external-rendering or image round-trip and later treated as
            # ordinary public information.
            #
            if (
                descriptor.external_sink
                and value.label.sensitivity
                >= Sensitivity.USER_PRIVATE
            ):
                return ChainValidation(
                    allowed=False,
                    reason=(
                        "high-sensitivity information reached "
                        "external capability"
                    ),
                    path=ordered,
                )

        return ChainValidation(
            allowed=True,
            reason="allowed",
            path=ordered,
            required_verifiers=frozenset(
                required
            ),
        )


def default_capability_graph() -> CapabilityGraph:
    graph = CapabilityGraph()

    graph.register(
        CapabilityDescriptor(
            capability_id="local_reasoning",
            #
            # Local reasoning may inspect secret material.
            #
            # This does NOT authorize disclosure. Sensitivity and provenance
            # remain attached to transformed values, and later external sinks
            # independently enforce their lower information-flow ceiling.
            #
            maximum_input_sensitivity=(
                Sensitivity.SYSTEM_SECRET
            ),
            maximum_output_sensitivity=(
                Sensitivity.SYSTEM_SECRET
            ),
            required_verifiers=frozenset(
                {
                    "schema",
                }
            ),
        )
    )

    graph.register(
        CapabilityDescriptor(
            capability_id="local_filesystem",
            maximum_input_sensitivity=(
                Sensitivity.USER_PRIVATE
            ),
            maximum_output_sensitivity=(
                Sensitivity.USER_PRIVATE
            ),
            persistent_sink=True,
            side_effects=frozenset(
                {
                    "filesystem_write",
                }
            ),
            required_verifiers=frozenset(
                {
                    "workspace_boundary",
                }
            ),
        )
    )

    graph.register(
        CapabilityDescriptor(
            capability_id="browser_network",
            maximum_input_sensitivity=(
                Sensitivity.INTERNAL
            ),
            maximum_output_sensitivity=(
                Sensitivity.INTERNAL
            ),
            external_sink=True,
            side_effects=frozenset(
                {
                    "network",
                }
            ),
            required_verifiers=frozenset(
                {
                    "network_policy",
                }
            ),
        )
    )

    graph.register(
        CapabilityDescriptor(
            capability_id="image_render",
            maximum_input_sensitivity=(
                Sensitivity.INTERNAL
            ),
            maximum_output_sensitivity=(
                Sensitivity.INTERNAL
            ),
            external_sink=True,
            required_verifiers=frozenset(
                {
                    "information_flow",
                }
            ),
        )
    )

    graph.register(
        CapabilityDescriptor(
            capability_id="ocr_decode",
            maximum_input_sensitivity=(
                Sensitivity.INTERNAL
            ),
            maximum_output_sensitivity=(
                Sensitivity.INTERNAL
            ),
            required_verifiers=frozenset(
                {
                    "provenance",
                }
            ),
        )
    )

    graph.register(
        CapabilityDescriptor(
            capability_id="agentic_memory",
            maximum_input_sensitivity=(
                Sensitivity.USER_PRIVATE
            ),
            maximum_output_sensitivity=(
                Sensitivity.USER_PRIVATE
            ),
            persistent_sink=True,
            required_verifiers=frozenset(
                {
                    "memory_evidence",
                }
            ),
        )
    )

    graph.connect(
        "local_reasoning",
        "local_filesystem",
    )

    graph.connect(
        "local_reasoning",
        "browser_network",
    )

    graph.connect(
        "browser_network",
        "image_render",
    )

    graph.connect(
        "image_render",
        "ocr_decode",
    )

    graph.connect(
        "ocr_decode",
        "agentic_memory",
    )

    graph.connect(
        "local_reasoning",
        "agentic_memory",
    )

    return graph


__all__ = [
    "CapabilityEdge",
    "CapabilityGraph",
    "CapabilityNode",
    "ChainValidation",
    "default_capability_graph",
]
