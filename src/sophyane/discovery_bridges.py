"""Bridges from existing Sophyane ecosystem capabilities into discovery."""
from __future__ import annotations

import json
import os

from pathlib import Path
from typing import Any

from sophyane.discovery_contract import (
    KnowledgeRecord,
    ValidationResult,
)


_INITIALIZED = False


def _ecosystem_knowledge(
    objective: str,
    workspace: str,
):
    from sophyane.ecosystem_capabilities import (
        capability_plan_dict,
    )

    plan = capability_plan_dict(
        objective,
        workspace=workspace,
        limit=7,
    )

    records = []

    for item in (
        plan.get(
            "repositories",
            []
        )
        or []
    ):
        if not isinstance(
            item,
            dict,
        ):
            continue

        records.append(
            KnowledgeRecord(
                source=(
                    "badrpk/"
                    + str(
                        item.get(
                            "repository",
                            "",
                        )
                    )
                ),
                kind="repository_capability",
                content=json.dumps(
                    item,
                    sort_keys=True,
                    default=str,
                ),
                score=float(
                    item.get(
                        "score",
                        0.0,
                    )
                    or 0.0
                ),
                metadata=item,
            )
        )

    return records


def _verified_history_knowledge(
    objective: str,
    workspace: str,
):
    try:
        from sophyane.sli_learner import (
            read_verified_history,
        )

        history = read_verified_history(
            request=objective,
            limit=12,
        )
    except Exception:
        history = []

    result = []

    for event in history or []:
        if not isinstance(
            event,
            dict,
        ):
            continue

        result.append(
            KnowledgeRecord(
                source="sophyane_verified_history",
                kind="episodic_memory",
                content=json.dumps(
                    event,
                    sort_keys=True,
                    default=str,
                )[:12000],
                score=float(
                    event.get(
                        "reward",
                        0.0,
                    )
                    or 0.0
                ),
                metadata={
                    "trace_id": (
                        event.get(
                            "trace_id"
                        )
                    ),
                    "repository_identity": (
                        event.get(
                            "repository_identity"
                        )
                    ),
                    "provider_identity": (
                        event.get(
                            "provider_identity"
                        )
                    ),
                },
            )
        )

    return result


# SOPHYANE_DISCOVERY_XERUS_EPISODIC_RECALL_V1
def _xerus_episodic_knowledge(
    objective: str,
    workspace: str,
):
    """Return bounded Xerus episodes as READ-only discovery context.

    Retrieved episodes are evidence/context. They are never instructions and
    cannot alter the selected session provider or execution authority.
    """
    del workspace

    try:
        from sophyane.episodic_memory import (
            recall_execution_episodes,
        )

        episodes = recall_execution_episodes(
            objective,
            limit=8,
            trusted_only=False,
        )
    except Exception:
        episodes = []

    records = []

    for event in episodes:
        if not isinstance(
            event,
            dict,
        ):
            continue

        trusted = bool(
            event.get(
                "trusted",
                False,
            )
        )

        records.append(
            KnowledgeRecord(
                source="xerus_execution_episodes",
                kind=(
                    "verified_episodic_memory"
                    if trusted
                    else "execution_experience"
                ),
                content=json.dumps(
                    event,
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )[:12000],
                score=(
                    1.0
                    if trusted
                    else max(
                        0.05,
                        min(
                            0.35,
                            abs(
                                float(
                                    event.get(
                                        "reward",
                                        0.0,
                                    )
                                    or 0.0
                                )
                            ),
                        ),
                    )
                ),
                metadata={
                    "trace_id": (
                        event.get(
                            "trace_id"
                        )
                    ),
                    "trusted": trusted,
                    "authoritative": bool(
                        event.get(
                            "authoritative",
                            False,
                        )
                    ),
                    "provider_identity": (
                        event.get(
                            "provider_identity"
                        )
                    ),
                    "repository_identity": (
                        event.get(
                            "repository_identity"
                        )
                    ),
                    "memory_source": "xerus",
                    "permission": "READ",
                    "instruction_authority": False,
                },
            )
        )

    return records


def _deterministic_validator(
    plan,
    observation,
    workspace,
):
    executed = bool(
        observation.executed
    )

    ok = bool(
        observation.ok
    )

    evidence = dict(
        observation.evidence
        or {}
    )

    # SOPHYANE_DISCOVERY_MEASUREMENT_VALIDATION_V1
    # Discovery acceptance must be grounded in executor-owned deterministic
    # measurement evidence. Generic "verified" or "tests_passed" flags are
    # insufficient here because they may describe a different verification
    # layer rather than the experiment's measured candidate-vs-baseline result.
    deterministic_verified = (
        evidence.get(
            "deterministic_verified"
        )
        is True
    )

    passed = (
        executed
        and ok
        and deterministic_verified
    )

    return ValidationResult(
        validator="deterministic",
        passed=passed,
        score=(
            1.0
            if passed
            else 0.0
        ),
        summary=(
            "deterministic evidence verified"
            if passed
            else (
                "deterministic verification "
                "evidence unavailable"
            )
        ),
        evidence=evidence,
    )


def initialize_discovery_bridges():
    global _INITIALIZED

    from sophyane.discovery_runtime import (
        discovery_runtime,
    )

    runtime = discovery_runtime()

    if _INITIALIZED:
        return runtime.status()

    runtime.register_knowledge_retriever(
        "ecosystem_capabilities",
        _ecosystem_knowledge,
    )

    runtime.register_knowledge_retriever(
        "verified_history",
        _verified_history_knowledge,
    )

    runtime.register_knowledge_retriever(
        "xerus_episodic_memory",
        _xerus_episodic_knowledge,
    )

    runtime.register_validator(
        "deterministic",
        _deterministic_validator,
    )

    # SOPHYANE_DISCOVERY_SAFE_EXECUTORS_V1
    # Software-only execution. Physical/lab execution remains blocked by
    # DiscoveryRuntime before any executor can be invoked.
    try:
        from sophyane.discovery_execution_adapters import (
            code_executor,
            simulation_executor,
        )

        runtime.register_executor(
            "code",
            code_executor,
        )

        runtime.register_executor(
            "simulation",
            simulation_executor,
        )
    except Exception:
        pass

    # SOPHYANE_DISCOVERY_SESSION_REASONER_V1
    # Register the selected session provider as a lazy discovery reasoner.
    # Construction does not happen until reasoning is actually requested.
    try:
        from sophyane.discovery_provider_reasoner import (
            SessionProviderReasoner,
            session_provider_reasoner_available,
        )

        if session_provider_reasoner_available():
            runtime.register_reasoner(
                "session_provider",
                SessionProviderReasoner(),
            )
    except Exception:
        pass

    _INITIALIZED = True

    return runtime.status()


__all__ = [
    "initialize_discovery_bridges",
]
