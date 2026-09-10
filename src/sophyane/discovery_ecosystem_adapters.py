"""Discovery adapter probes for Badrpk ecosystem repositories.

This module reports only verified callable availability. It deliberately does
not guess Neuron, Xerus, or NIFDU runtime APIs.
"""
from __future__ import annotations

import importlib
import json

from dataclasses import (
    asdict,
    dataclass,
)
from typing import Any


@dataclass(
    frozen=True
)
class AdapterProbe:
    repository: str
    available: bool
    module: str
    callable_name: str
    reason: str

    def to_dict(
        self,
    ) -> dict[str, Any]:
        return asdict(
            self
        )


# Known names are intentionally narrow. If a repository changes its runtime
# API, the adapter remains unavailable rather than guessing.
_CANDIDATES = {
    "neuron": (
        (
            "neuron",
            "adapt",
        ),
        (
            "neuron.api",
            "adapt",
        ),
        (
            "neuron.runtime",
            "adapt",
        ),
    ),
    "xerus": (
        (
            "xerus",
            "retrieve",
        ),
        (
            "xerus.api",
            "retrieve",
        ),
        (
            "xerus.runtime",
            "retrieve",
        ),
    ),
    "nifdu": (
        (
            "nifdu",
            "judge",
        ),
        (
            "nifdu.api",
            "judge",
        ),
        (
            "nifdu.runtime",
            "judge",
        ),
    ),
}


def probe_repository_adapter(
    repository: str,
) -> AdapterProbe:
    repo = str(
        repository
        or ""
    ).strip().lower()

    candidates = (
        _CANDIDATES.get(
            repo,
            (),
        )
    )

    for (
        module_name,
        callable_name,
    ) in candidates:
        try:
            module = importlib.import_module(
                module_name
            )
        except Exception:
            continue

        candidate = getattr(
            module,
            callable_name,
            None,
        )

        if callable(
            candidate
        ):
            return AdapterProbe(
                repository=repo,
                available=True,
                module=module_name,
                callable_name=(
                    callable_name
                ),
                reason=(
                    "CALLABLE_CONTRACT_VERIFIED"
                ),
            )

    return AdapterProbe(
        repository=repo,
        available=False,
        module="",
        callable_name="",
        reason=(
            "NO_VERIFIED_CALLABLE_CONTRACT"
        ),
    )


def probe_discovery_ecosystem(
) -> dict[str, AdapterProbe]:
    return {
        repo: probe_repository_adapter(
            repo
        )
        for repo in (
            "neuron",
            "xerus",
            "nifdu",
        )
    }


def status_dict(
) -> dict[str, dict[str, Any]]:
    return {
        name: probe.to_dict()
        for (
            name,
            probe,
        ) in (
            probe_discovery_ecosystem()
            .items()
        )
    }


__all__ = [
    "AdapterProbe",
    "probe_discovery_ecosystem",
    "probe_repository_adapter",
    "status_dict",
]
