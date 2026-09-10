"""Builtin adapters for peers with an explicit safe integration.

Do not infer executable commands from README text.

An adapter is registered only where Sophyane already has a canonical
integration surface.
"""
from __future__ import annotations

from typing import Any


_INITIALIZED = False


def initialize_peer_adapters() -> tuple[str, ...]:
    global _INITIALIZED

    from sophyane.peer_capability_adapter import (
        peer_adapter_catalog,
    )

    if _INITIALIZED:
        return peer_adapter_catalog()

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
    "peer_runtime_status",
]
