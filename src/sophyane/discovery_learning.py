"""Persist discovery episodes through Sophyane's existing learning layer."""
from __future__ import annotations

import hashlib
import json
import time

from pathlib import Path
from typing import Any

from sophyane.discovery_contract import (
    DiscoveryEpisode,
)


def record_discovery_episode(
    episode: DiscoveryEpisode,
    *,
    workspace: str | Path,
) -> dict[str, Any] | None:
    objective = str(
        episode.objective
        or ""
    )

    objective_hash = hashlib.sha256(
        objective.encode(
            "utf-8"
        )
    ).hexdigest()

    accepted = bool(
        episode.accepted_candidates
    )

    provenance = {
        "trace_id": episode.episode_id,
        "event_type": "discovery_episode",
        "original_objective": objective,
        "objective_hash": objective_hash,
        "status": (
            "succeeded"
            if accepted
            else "inconclusive"
        ),
        "accepted": accepted,
        "verification_state": (
            "verified"
            if accepted
            else "unverified"
        ),
        "verification_evidence": [
            {
                "candidate_id": (
                    result.candidate.candidate_id
                ),
                "reproduced": (
                    result.reproduced
                ),
                "final_novelty_score": (
                    result.final_novelty_score
                ),
                "validators": [
                    item.to_dict()
                    for item
                    in result.validations
                ],
            }
            for result
            in episode.results
        ],
        "repository_identity": None,
        "provider_identity": None,
        "capability_class": (
            "discovery_engine"
        ),
        "reward": (
            1.0
            if accepted
            else -0.05
        ),
        "result": json.dumps(
            episode.to_dict(),
            sort_keys=True,
            default=str,
        )[:16000],
        "created_at": time.time(),
    }

    try:
        from sophyane.sli_learner import (
            learn_execution,
        )

        learned = learn_execution(
            trace_id=episode.episode_id,
            request=objective,
            workspace_before={},
            workspace_after={},
            status=provenance[
                "status"
            ],
            reward=float(
                provenance[
                    "reward"
                ]
            ),
            result=provenance[
                "result"
            ],
            elapsed_seconds=max(
                0.0,
                episode.finished_at
                - episode.started_at,
            ),
            provenance=provenance,
        )
    except Exception:
        return None

    event = provenance

    if isinstance(
        learned,
        dict,
    ):
        candidate = learned.get(
            "provenance"
        )

        if isinstance(
            candidate,
            dict,
        ):
            event = candidate

    if (
        event.get(
            "accepted"
        )
        is True
        and str(
            event.get(
                "verification_state",
                "",
            )
        ).casefold()
        == "verified"
    ):
        try:
            from sophyane.durable_memory import (
                remember_verified_execution,
            )

            remember_verified_execution(
                event
            )
        except Exception:
            pass

    return event


__all__ = [
    "record_discovery_episode",
]
