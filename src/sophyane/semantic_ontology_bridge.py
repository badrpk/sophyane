"""Optional bridge: expand learned ontology before SLI consultation."""
from __future__ import annotations

from typing import Any


def enrich_request_semantics(request: str) -> dict[str, Any]:
    try:
        from sophyane.semantic_ontology_learner import expand_for_request

        return expand_for_request(request)
    except Exception as exc:  # never break the agent
        return {"error": str(exc), "temporary": {}, "unknown": []}


def note_execution_success(request: str) -> dict[str, Any]:
    try:
        from sophyane.semantic_ontology_learner import record_success

        return record_success(request)
    except Exception as exc:
        return {"error": str(exc), "promoted": []}
