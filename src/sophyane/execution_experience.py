"""Provider-neutral structured execution experience recording.

Every execution may become experience.

Only deterministically verified success becomes trusted/accepted memory.
Failures and unverified successes remain useful routing evidence without
being promoted to trusted solution memory.
"""
from __future__ import annotations

import hashlib
import json
import os
import time

from pathlib import Path
from typing import Any


_SUCCESS = {
    "success",
    "succeeded",
    "completed",
}


def session_authority() -> dict[str, str]:
    return {
        "session_mode": str(
            os.environ.get(
                "SOPHYANE_SESSION_MODE",
                "",
            )
            or ""
        ).strip(),
        "session_provider": str(
            os.environ.get(
                "SOPHYANE_SESSION_PROVIDER",
                "",
            )
            or ""
        ).strip(),
        "session_model": str(
            os.environ.get(
                "SOPHYANE_SESSION_MODEL",
                "",
            )
            or ""
        ).strip(),
    }


def _verified(
    evidence: object,
) -> tuple[bool, list[dict[str, Any]]]:
    if not isinstance(
        evidence,
        dict,
    ):
        return False, []

    records: list[dict[str, Any]] = []

    data = evidence.get(
        "data"
    )

    if isinstance(
        data,
        dict,
    ):
        records.append(
            dict(data)
        )

        if data.get(
            "byte_for_byte_verified"
        ) is True:
            return True, records

        if (
            str(
                data.get(
                    "verification_state",
                    "",
                )
            ).casefold()
            == "verified"
            and bool(
                data.get(
                    "verification_evidence"
                )
            )
        ):
            return True, records

    state = str(
        evidence.get(
            "verification_state",
            "",
        )
        or ""
    ).casefold()

    raw = evidence.get(
        "verification_evidence"
    )

    if isinstance(
        raw,
        list,
    ):
        for item in raw:
            if isinstance(
                item,
                dict,
            ):
                records.append(
                    dict(item)
                )

    if (
        state == "verified"
        and records
    ):
        return True, records

    return False, records


def _snapshot(
    workspace: str | Path,
) -> dict[str, Any]:
    try:
        from sophyane.runtime_orchestration_patch import (
            _snapshot as runtime_snapshot,
        )

        value = runtime_snapshot(
            Path(workspace)
        )

        if isinstance(
            value,
            dict,
        ):
            return value
    except Exception:
        pass

    return {}


def _repository_plan(
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    value = metadata.get(
        "badrpk_capability_plan"
    )

    if not isinstance(
        value,
        dict,
    ):
        return []

    ranked = value.get(
        "repositories"
    )

    if not isinstance(
        ranked,
        list,
    ):
        return []

    return [
        dict(item)
        for item in ranked
        if isinstance(
            item,
            dict,
        )
    ]


def _executed_repository(
    *,
    metadata: dict[str, Any],
    evidence: dict[str, Any],
) -> str | None:
    """Return only a repository proven to have participated.

    Ranked capability candidates are advisory and must never receive
    execution credit merely because they ranked highly.
    """
    candidates = (
        evidence.get(
            "repository_identity"
        ),
        evidence.get(
            "executed_repository"
        ),
        metadata.get(
            "executed_repository"
        ),
        metadata.get(
            "repository_identity"
        ),
    )

    provenance = evidence.get(
        "provenance"
    )

    if isinstance(
        provenance,
        dict,
    ):
        candidates = (
            *candidates,
            provenance.get(
                "repository_identity"
            ),
            provenance.get(
                "executed_repository"
            ),
        )

    for raw in candidates:
        value = str(
            raw
            or ""
        ).strip()

        if not value:
            continue

        if value.casefold().startswith(
            "badrpk/"
        ):
            return value

        return (
            "badrpk/"
            + value
        )

    return None


def _reward(
    *,
    handled: bool,
    ok: bool,
    verified: bool,
) -> float:
    if verified and ok:
        return 1.0

    if ok:
        return 0.35

    if handled:
        return -0.50

    return -0.10


def record_execution_experience(
    *,
    request_text: str,
    workspace: str | Path,
    result: object,
    metadata: dict[str, Any] | None = None,
    workspace_before: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Record one execution attempt into the existing SLI learner.

    This function must never decide task success and must never raise into
    the user-facing execution path.
    """
    meta = dict(
        metadata
        or {}
    )

    handled = bool(
        getattr(
            result,
            "handled",
            False,
        )
    )

    ok = bool(
        getattr(
            result,
            "ok",
            False,
        )
    )

    capability = str(
        getattr(
            result,
            "capability",
            "",
        )
        or ""
    )

    output = str(
        getattr(
            result,
            "output",
            "",
        )
        or ""
    )

    evidence = getattr(
        result,
        "evidence",
        {},
    )

    if not isinstance(
        evidence,
        dict,
    ):
        evidence = {}

    verified, verification_evidence = (
        _verified(
            evidence
        )
    )

    started_at = getattr(
        result,
        "started_at",
        None,
    )

    finished_at = getattr(
        result,
        "finished_at",
        None,
    )

    try:
        elapsed = max(
            0.0,
            float(finished_at)
            - float(started_at),
        )
    except (
        TypeError,
        ValueError,
    ):
        elapsed = 0.0

    status = (
        "succeeded"
        if ok
        else (
            "failed"
            if handled
            else "unhandled"
        )
    )

    plan = _repository_plan(
        meta
    )

    authority = session_authority()

    after = _snapshot(
        workspace
    )

    before = (
        workspace_before
        if isinstance(
            workspace_before,
            dict,
        )
        else {}
    )

    objective = str(
        request_text
        or ""
    )

    objective_hash = hashlib.sha256(
        objective.encode(
            "utf-8"
        )
    ).hexdigest()

    trace_material = {
        "objective_hash": objective_hash,
        "workspace": str(
            workspace
        ),
        "capability": capability,
        "status": status,
        "authority": authority,
        "repositories": [
            item.get(
                "repository"
            )
            for item in plan
        ],
        "time_ns": time.time_ns(),
    }

    trace_id = (
        "ecosystem-"
        + hashlib.sha256(
            json.dumps(
                trace_material,
                sort_keys=True,
                separators=(
                    ",",
                    ":",
                ),
                default=str,
            ).encode(
                "utf-8"
            )
        ).hexdigest()[:32]
    )

    event: dict[str, Any] = {
        "trace_id": trace_id,
        "event_type": (
            "badrpk_ecosystem_execution"
        ),
        "objective_hash": objective_hash,
        "original_objective": objective,
        "status": status,
        "verification_state": (
            "verified"
            if verified
            else "unverified"
        ),
        "verification_evidence": (
            verification_evidence
        ),
        "accepted": bool(
            ok
            and verified
        ),
        "workspace": str(
            workspace
        ),
        "changed_paths": [],
        "artifact_paths": [],
        # Candidate ranking is preserved separately below.
        # Repository identity requires execution evidence.
        "repository_identity": (
            _executed_repository(
                metadata=meta,
                evidence=evidence,
            )
        ),
        "repository_candidates": plan,
        "provider_identity": (
            authority[
                "session_provider"
            ]
            or authority[
                "session_mode"
            ]
            or None
        ),
        "model_identity": (
            authority[
                "session_model"
            ]
            or None
        ),
        "session_mode": (
            authority[
                "session_mode"
            ]
        ),
        "capability_class": (
            capability
            or None
        ),
        "handled": handled,
        "result": output[:4000],
        "reward": _reward(
            handled=handled,
            ok=ok,
            verified=verified,
        ),
        "created_at": time.time(),
    }

    try:
        from sophyane.sli_learner import (
            learn_execution,
        )

        learned = learn_execution(
            trace_id=trace_id,
            request=objective,
            workspace_before=before,
            workspace_after=after,
            status=status,
            reward=float(
                event["reward"]
            ),
            result=event["result"],
            elapsed_seconds=elapsed,
            provenance=event,
        )
    except Exception:
        # SOPHYANE_XERUS_EXECUTION_EPISODE_PERSISTENCE_V1
        # Xerus is an independent durable episode sink. A failure in the
        # existing SLI learner must not prevent retention of the execution
        # attempt, and Xerus failure must never escape into task execution.
        try:
            from sophyane.episodic_memory import (
                persist_execution_episode,
            )

            persist_execution_episode(
                event
            )
        except Exception:
            pass

        return None

    if not isinstance(
        learned,
        dict,
    ):
        try:
            from sophyane.episodic_memory import (
                persist_execution_episode,
            )

            persist_execution_episode(
                event
            )
        except Exception:
            pass

        return event

    provenance = learned.get(
        "provenance"
    )

    if isinstance(
        provenance,
        dict,
    ):
        event = provenance

    # Persist the canonical learned provenance when available. Xerus stores
    # both positive and negative experience, but only accepted + verified
    # episodes are marked trusted/authoritative by episodic_memory.
    try:
        from sophyane.episodic_memory import (
            persist_execution_episode,
        )

        persist_execution_episode(
            event
        )
    except Exception:
        pass

    # Only trusted verified success is promoted into durable trusted memory.
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
    "record_execution_experience",
    "session_authority",
]
