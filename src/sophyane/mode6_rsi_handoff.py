"""Guarded Mode-6 improvement observation handoff.

Conversation LLM observations are untrusted diagnostic evidence only.
This module may append them to Sophyane's improvement proposal ledger.
It also queues an untrusted autonomous observation. It never executes a candidate, grants
mutation authority, or invokes promotion.
"""

from __future__ import annotations

from typing import Any

from sophyane.human_conversation import (
    ImprovementObservation,
)
from sophyane.self_improve import ledger
from sophyane.rsi.observation_bus import (
    autonomous_bus, ImprovementObservation as RSIObservation, ImprovementSource,
)


def record_mode6_improvement_observation(
    observation: ImprovementObservation | None,
) -> dict[str, Any]:
    """Persist one untrusted observation as a non-executing code hint."""

    if observation is None:
        return {
            "ok": True,
            "recorded": False,
            "reason": "no_observation",
        }

    if (
        observation.trusted
        or observation.instruction_authority
        or observation.mutation_authority
    ):
        return {
            "ok": False,
            "recorded": False,
            "reason": "observation_has_authority",
        }

    submitted = autonomous_bus.submit(RSIObservation(
        ImprovementSource.MODE6, observation.problem, observation.component,
        observation.evidence, observation.suggested_direction,
    ))

    title = (
        "Mode 6 observation: "
        + observation.component
    )[:200]

    body = (
        "Problem:\n"
        + observation.problem
        + "\n\nEvidence:\n- "
        + "\n- ".join(
            observation.evidence
        )
        + "\n\nSuggested direction:\n"
        + observation.suggested_direction
    )

    evidence = {
        "source": "mode6_conversation",
        "component": observation.component,
        "source_mutation_required": (
            observation.source_mutation_required
        ),
        "trusted": False,
        "instruction_authority": False,
        "mutation_authority": False,
        "requires_grounded_weakness": True,
        "observation_evidence": list(
            observation.evidence
        ),
    }

    try:
        result = ledger.propose_improvement(
            "code_hint",
            title,
            body,
            evidence=evidence,
            score=0.0,
        )
    except Exception as exc:
        return {
            "ok": False,
            "recorded": False,
            "reason": "ledger_error",
            "error": (
                type(exc).__name__
                + ": "
                + str(exc)
            ),
        }

    return {
        **dict(result),
        "recorded": bool(
            result.get(
                "ok",
                False,
            )
        ),
        "handoff": "improvement_ledger_only",
        "autonomous_submitted": submitted,
    }


__all__ = [
    "record_mode6_improvement_observation",
]
