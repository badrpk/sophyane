"""Typed Badrpk ecosystem capability graph."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CapabilityNode:
    repository: str
    role: str
    capabilities: tuple[str, ...]
    available: bool
    execution_ready: bool
    source: str
    root: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapabilityEdge:
    source: str
    target: str
    capability: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EcosystemGraph:
    nodes: tuple[CapabilityNode, ...]
    edges: tuple[CapabilityEdge, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [
                item.to_dict()
                for item in self.nodes
            ],
            "edges": [
                item.to_dict()
                for item in self.edges
            ],
        }


def build_ecosystem_graph(
    *,
    workspace: str | Path | None = None,
    remote_loader=None,
) -> EcosystemGraph:
    from sophyane.ecosystem_capabilities import (
        discover_badrpk_capabilities,
    )
    from sophyane.ecosystem_contract import (
        load_local_manifest,
        load_remote_manifest,
    )

    catalog = (
        discover_badrpk_capabilities(
            workspace=workspace,
            remote_loader=remote_loader,
        )
    )

    nodes = tuple(
        CapabilityNode(
            repository=item.repository,
            role=item.role,
            capabilities=item.capabilities,
            available=item.available,
            execution_ready=item.execution_ready,
            source=item.source,
            root=item.root,
        )
        for item in catalog
    )

    edges: set[
        tuple[str, str, str]
    ] = set()

    for item in catalog:
        manifest = None

        if item.local_available and item.root:
            manifest = load_local_manifest(
                item.root,
                repository=item.repository,
            )

        if manifest is None:
            manifest = load_remote_manifest(
                item.repository,
                loader=remote_loader,
            )

        if manifest is None:
            continue

        for peer, capability in manifest.peers:
            edges.add(
                (
                    item.repository,
                    peer,
                    capability,
                )
            )

    return EcosystemGraph(
        nodes=nodes,
        edges=tuple(
            CapabilityEdge(
                source=source,
                target=target,
                capability=capability,
            )
            for source, target, capability
            in sorted(edges)
        ),
    )


def support_nodes_for_objective(
    objective: str,
    *,
    workspace: str | Path | None = None,
    limit: int = 4,
) -> list[dict[str, Any]]:
    from sophyane.ecosystem_capabilities import (
        rank_badrpk_capabilities,
    )

    return [
        item.to_dict()
        for item in rank_badrpk_capabilities(
            objective,
            workspace=workspace,
            limit=limit,
        )
    ]


__all__ = [
    "CapabilityEdge",
    "CapabilityNode",
    "EcosystemGraph",
    "build_ecosystem_graph",
    "support_nodes_for_objective",
]
