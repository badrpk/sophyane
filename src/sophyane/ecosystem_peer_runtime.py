"""Builtin adapters for peers with an explicit safe integration.

Do not infer executable commands from README text.

An adapter is registered only where Sophyane already has a canonical
integration surface.
"""
from __future__ import annotations

from typing import Any
from pathlib import Path


_INITIALIZED = False


def register_local_peer_adapters(
    *,
    roots: tuple[str | Path, ...] | list[str | Path] | None = None,
) -> tuple[str, ...]:
    from sophyane.ecosystem_capabilities import discover_badrpk_capabilities
    from sophyane.ecosystem_contract import load_local_manifest
    from sophyane.peer_capability_adapter import (
        register_peer_adapter,
        unregister_peer_adapter,
    )
    from sophyane.peer_process_adapter import LocalPeerProcessAdapter

    discovered = discover_badrpk_capabilities(roots=roots)
    registered: list[str] = []
    for item in discovered:
        if not item.local_available:
            continue
        unregister_peer_adapter(repository=item.repository)
        if not item.contract_valid or not item.root:
            continue
        manifest = load_local_manifest(item.root, repository=item.repository)
        if manifest is None or not manifest.operations:
            continue
        operations = {
            name: operation
            for name, operation in manifest.operations
            if LocalPeerProcessAdapter.executable_available(operation.argv)
        }
        if not operations:
            continue
        adapter = LocalPeerProcessAdapter(
            item.repository,
            Path(item.root),
            operations,
        )
        register_peer_adapter(
            repository=item.repository,
            capabilities=tuple(operations),
            invoker=adapter.invoke,
        )
        registered.append(item.repository)
    return tuple(sorted(set(registered)))


def initialize_peer_adapters() -> tuple[str, ...]:
    global _INITIALIZED

    from sophyane.peer_capability_adapter import (
        peer_adapter_catalog,
    )

    if _INITIALIZED:
        return peer_adapter_catalog()

    register_local_peer_adapters()

    # NIFDU already has a Sophyane-native provider/guarded integration.
    # Do not create a second subprocess implementation here. The graph
    # records its capabilities while the existing NIFDU path remains the
    # execution authority.
    #
    # Xerus/Neuron/Shmry/Veyron/etc. will be registered once they expose
    # a stable callable operation contract, rather than guessing CLI
    # semantics from documentation.

    _INITIALIZED = True

    return peer_adapter_catalog()


def peer_runtime_status() -> dict[str, Any]:
    from sophyane.ecosystem_capabilities import (
        discover_badrpk_capabilities,
    )
    from sophyane.peer_capability_adapter import (
        peer_adapter_catalog,
    )

    initialize_peer_adapters()

    registered = set(
        peer_adapter_catalog()
    )

    components = []

    for item in (
        discover_badrpk_capabilities()
    ):
        components.append(
            {
                "repository": item.repository,
                "available": item.available,
                "execution_ready": (
                    item.execution_ready
                ),
                "adapter_registered": (
                    item.repository
                    in registered
                ),
                "source": item.source,
                "role": item.role,
                "capabilities": list(
                    item.capabilities
                ),
            }
        )

    return {
        "registered_adapters": sorted(
            registered
        ),
        "components": components,
    }


__all__ = [
    "initialize_peer_adapters",
    "register_local_peer_adapters",
    "peer_runtime_status",
]
