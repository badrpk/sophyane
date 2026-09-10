import json


def _remote_loader(
    repository,
    relative,
):
    manifests = {
        "neuron": {
            "schema": "sophyane-ecosystem-v1",
            "component": "neuron",
            "role": "biological-intelligence",
            "aliases": [
                "neutron",
            ],
            "capabilities": [
                "biological-intelligence",
                "learning",
                "neural-adaptation",
                "embedding-support",
            ],
            "peers": {
                "xerus": "disk-first-memory",
                "nifdu": "screenshot-loop-harness",
            },
            "routing": {
                "policy": (
                    "request-peer-capability-when-"
                    "local-capability-is-missing"
                ),
                "transport": [
                    "local-process",
                    "http-json",
                ],
                "fallback": (
                    "return-explicit-capability-unavailable"
                ),
            },
        },
        "xerus": {
            "schema": "sophyane-ecosystem-v1",
            "component": "xerus",
            "role": "disk-first-memory",
            "capabilities": [
                "persistent-memory",
                "retrieval",
                "storage-index",
            ],
            "peers": {
                "neuron": "biological-intelligence",
            },
            "routing": {
                "transport": [
                    "local-process",
                ]
            },
        },
    }

    if relative == "ecosystem.json":
        value = manifests.get(
            repository
        )

        return (
            json.dumps(value)
            if value is not None
            else ""
        )

    if relative == "README.md":
        if repository == "nifdu":
            return (
                "NIFDU browser screenshot visual verification "
                "repair harness"
            )

    return ""


def test_remote_manifest_is_discoverable_but_not_execution_ready(
    tmp_path,
):
    from sophyane.ecosystem_capabilities import (
        discover_badrpk_capabilities,
    )

    catalog = (
        discover_badrpk_capabilities(
            roots=[tmp_path],
            remote_loader=_remote_loader,
        )
    )

    neuron = next(
        item
        for item in catalog
        if item.repository == "neuron"
    )

    assert neuron.available is True
    assert neuron.remote_available is True
    assert neuron.local_available is False
    assert neuron.execution_ready is False
    assert neuron.contract_valid is True
    assert (
        "biological-intelligence"
        in neuron.capabilities
    )


def test_manifest_capabilities_drive_semantic_ranking(
    tmp_path,
):
    from sophyane.ecosystem_capabilities import (
        discover_badrpk_capabilities,
        rank_badrpk_capabilities,
    )

    catalog = (
        discover_badrpk_capabilities(
            roots=[tmp_path],
            remote_loader=_remote_loader,
        )
    )

    ranked = (
        rank_badrpk_capabilities(
            (
                "Use persistent memory retrieval and "
                "storage indexing"
            ),
            capabilities=catalog,
            history_reader=lambda **_: [],
            limit=3,
        )
    )

    assert ranked
    assert ranked[0].repository == "xerus"


def test_graph_contains_peer_capability_edges(
    tmp_path,
):
    from sophyane.ecosystem_graph import (
        build_ecosystem_graph,
    )

    graph = build_ecosystem_graph(
        workspace=tmp_path,
        remote_loader=_remote_loader,
    )

    edges = {
        (
            item.source,
            item.target,
            item.capability,
        )
        for item in graph.edges
    }

    assert (
        "neuron",
        "xerus",
        "disk-first-memory",
    ) in edges

    assert (
        "neuron",
        "nifdu",
        "screenshot-loop-harness",
    ) in edges
