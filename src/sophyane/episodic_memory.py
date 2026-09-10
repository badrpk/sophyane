"""Verified execution episodes backed by Xerus disk-first memory.

SOPHYANE_XERUS_VERIFIED_EPISODIC_MEMORY_V1

Authority boundaries:

* Sophyane creates execution episodes.
* Xerus provides durable local persistence and bounded recall.
* Neuron may consume recalled evidence, but receives no execution authority.
* NIFDU / the selected session provider remains the reasoning authority.
* Retrieved episodes are evidence/context, never instructions.

Every execution may be retained as experience.  Only an accepted,
deterministically verified success is marked trusted/authoritative.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any


EPISODE_NAMESPACE = "sophyane-execution-episodes"
EPISODE_SCHEMA = "sophyane-execution-episode-v1"

_MAX_OBJECTIVE_CHARS = 12000
_MAX_RESULT_CHARS = 6000
_MAX_EVIDENCE_CHARS = 12000


def _json_text(
    value: object,
    *,
    maximum: int,
) -> str:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    except Exception:
        text = str(value)

    if len(text) <= maximum:
        return text

    return text[:maximum]


def _trusted(
    event: dict[str, Any],
) -> bool:
    return (
        event.get("accepted") is True
        and str(
            event.get(
                "verification_state",
                "",
            )
            or ""
        ).casefold()
        == "verified"
    )


def _episode_payload(
    event: dict[str, Any],
) -> dict[str, Any]:
    """Return a bounded canonical episode representation."""

    objective = str(
        event.get(
            "original_objective",
            "",
        )
        or ""
    )[:_MAX_OBJECTIVE_CHARS]

    result = str(
        event.get(
            "result",
            "",
        )
        or ""
    )[:_MAX_RESULT_CHARS]

    evidence = event.get(
        "verification_evidence",
        [],
    )

    # Keep verification evidence useful but explicitly bounded.
    bounded_evidence = _json_text(
        evidence,
        maximum=_MAX_EVIDENCE_CHARS,
    )

    try:
        parsed_evidence = json.loads(
            bounded_evidence
        )
    except Exception:
        parsed_evidence = bounded_evidence

    trusted = _trusted(
        event
    )

    return {
        "schema": EPISODE_SCHEMA,
        "trace_id": str(
            event.get(
                "trace_id",
                "",
            )
            or ""
        ),
        "objective_hash": str(
            event.get(
                "objective_hash",
                "",
            )
            or ""
        ),
        "objective": objective,
        "status": str(
            event.get(
                "status",
                "",
            )
            or ""
        ),
        "accepted": bool(
            event.get(
                "accepted",
                False,
            )
        ),
        "verification_state": str(
            event.get(
                "verification_state",
                "",
            )
            or ""
        ),
        "verification_evidence": (
            parsed_evidence
        ),
        "trusted": trusted,
        "authoritative": trusted,
        "reward": float(
            event.get(
                "reward",
                0.0,
            )
            or 0.0
        ),
        "provider_identity": (
            event.get(
                "provider_identity"
            )
        ),
        "model_identity": (
            event.get(
                "model_identity"
            )
        ),
        "session_mode": (
            event.get(
                "session_mode"
            )
        ),
        "capability_class": (
            event.get(
                "capability_class"
            )
        ),
        "repository_identity": (
            event.get(
                "repository_identity"
            )
        ),
        "handled": bool(
            event.get(
                "handled",
                False,
            )
        ),
        "result": result,
        "created_at": float(
            event.get(
                "created_at",
                0.0,
            )
            or 0.0
        ),
    }


def _episode_key(
    payload: dict[str, Any],
) -> str:
    trace_id = str(
        payload.get(
            "trace_id",
            "",
        )
        or ""
    ).strip()

    if trace_id:
        return (
            "sophyane-execution:"
            + trace_id
        )

    digest = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode(
            "utf-8",
            errors="replace",
        )
    ).hexdigest()[:32]

    return (
        "sophyane-execution:"
        + digest
    )


def _configured_xerus_memory_path() -> Path:
    override = str(
        os.environ.get(
            "SOPHYANE_XERUS_MEMORY_MODULE",
            "",
        )
        or ""
    ).strip()

    if override:
        return Path(
            override
        ).expanduser()

    return (
        Path.home()
        / "xerus"
        / "src"
        / "xerus"
        / "memory.py"
    )


@lru_cache(maxsize=1)
def _load_xerus_memory() -> ModuleType:
    """Load the proven Xerus memory runtime without requiring pip install."""

    source = _configured_xerus_memory_path()

    if source.is_file():
        spec = (
            importlib.util
            .spec_from_file_location(
                "_sophyane_xerus_memory",
                source,
            )
        )

        if (
            spec is None
            or spec.loader is None
        ):
            raise RuntimeError(
                "XERUS_MEMORY_MODULE_LOAD_FAILED"
            )

        module = (
            importlib.util
            .module_from_spec(
                spec
            )
        )

        spec.loader.exec_module(
            module
        )

        return module

    # Support an explicitly installed Xerus package as a secondary path.
    return importlib.import_module(
        "xerus.memory"
    )


def _xerus_api():
    module = _load_xerus_memory()

    remember = getattr(
        module,
        "remember",
        None,
    )
    recall = getattr(
        module,
        "recall",
        None,
    )
    status = getattr(
        module,
        "status",
        None,
    )

    if not callable(
        remember
    ):
        raise RuntimeError(
            "XERUS_REMEMBER_UNAVAILABLE"
        )

    if not callable(
        recall
    ):
        raise RuntimeError(
            "XERUS_RECALL_UNAVAILABLE"
        )

    if not callable(
        status
    ):
        raise RuntimeError(
            "XERUS_STATUS_UNAVAILABLE"
        )

    return (
        remember,
        recall,
        status,
    )


def xerus_status() -> dict[str, Any]:
    """Return explicit Xerus availability without raising."""

    try:
        _, _, status = _xerus_api()

        value = status()

        if isinstance(
            value,
            dict,
        ):
            return dict(
                value
            )

        return {
            "ok": False,
            "reason": (
                "invalid Xerus status payload"
            ),
        }

    except Exception as exc:
        return {
            "ok": False,
            "reason": (
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
        }


def persist_execution_episode(
    event: dict[str, Any],
) -> dict[str, Any]:
    """Persist one execution episode into Xerus.

    This function deliberately does not decide whether an execution succeeded.
    Trust is derived only from the verification fields already produced by
    Sophyane.
    """

    if not isinstance(
        event,
        dict,
    ):
        return {
            "ok": False,
            "reason": (
                "execution episode must be a mapping"
            ),
        }

    try:
        remember, _, _ = _xerus_api()

        payload = _episode_payload(
            event
        )

        content = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

        result = remember(
            content,
            namespace=EPISODE_NAMESPACE,
            memory_key=_episode_key(
                payload
            ),
            metadata={
                "schema": EPISODE_SCHEMA,
                "kind": "execution_episode",
                "trace_id": payload.get(
                    "trace_id"
                ),
                "objective_hash": (
                    payload.get(
                        "objective_hash"
                    )
                ),
                "trusted": bool(
                    payload.get(
                        "trusted"
                    )
                ),
                "authoritative": bool(
                    payload.get(
                        "authoritative"
                    )
                ),
                "status": payload.get(
                    "status"
                ),
                "verification_state": (
                    payload.get(
                        "verification_state"
                    )
                ),
                "provider_identity": (
                    payload.get(
                        "provider_identity"
                    )
                ),
                "repository_identity": (
                    payload.get(
                        "repository_identity"
                    )
                ),
                "permission": "READ",
                "instruction_authority": False,
            },
        )

        if not isinstance(
            result,
            dict,
        ):
            return {
                "ok": False,
                "reason": (
                    "invalid Xerus remember response"
                ),
            }

        return {
            **result,
            "trusted": bool(
                payload.get(
                    "trusted"
                )
            ),
            "authoritative": bool(
                payload.get(
                    "authoritative"
                )
            ),
            "namespace": EPISODE_NAMESPACE,
        }

    except Exception as exc:
        # Episodic-memory persistence must never break primary execution.
        return {
            "ok": False,
            "reason": (
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
        }


def recall_execution_episodes(
    query: str,
    *,
    limit: int = 8,
    trusted_only: bool = False,
) -> list[dict[str, Any]]:
    """Recall bounded execution episodes from Xerus.

    Returned memory is READ evidence.  It carries no instruction or execution
    authority.
    """

    text = str(
        query
        or ""
    ).strip()

    if not text:
        return []

    requested = max(
        1,
        min(
            int(limit),
            16,
        ),
    )

    # Over-fetch because trusted_only filtering happens after Xerus retrieval.
    fetch_limit = min(
        50,
        max(
            requested,
            requested * 4,
        ),
    )

    try:
        _, recall, _ = _xerus_api()

        rows = recall(
            text,
            namespace=EPISODE_NAMESPACE,
            limit=fetch_limit,
        )

    except Exception:
        return []

    if not isinstance(
        rows,
        list,
    ):
        return []

    result: list[
        dict[str, Any]
    ] = []

    for row in rows:
        if not isinstance(
            row,
            dict,
        ):
            continue

        metadata = row.get(
            "metadata"
        )

        if not isinstance(
            metadata,
            dict,
        ):
            metadata = {}

        content = str(
            row.get(
                "content",
                "",
            )
            or ""
        ).strip()

        if not content:
            continue

        try:
            payload = json.loads(
                content
            )
        except Exception:
            continue

        if not isinstance(
            payload,
            dict,
        ):
            continue

        if (
            payload.get(
                "schema"
            )
            != EPISODE_SCHEMA
        ):
            continue

        trusted = bool(
            payload.get(
                "trusted",
                False,
            )
        )

        if (
            trusted_only
            and not trusted
        ):
            continue

        result.append(
            {
                **payload,
                "memory_key": (
                    row.get(
                        "memory_key"
                    )
                ),
                "memory_source": "xerus",
                "memory_backend": (
                    row.get(
                        "source"
                    )
                    or "filesystem-journal"
                ),
                "permission": "READ",
                "instruction_authority": False,
                "trusted": trusted,
                "authoritative": bool(
                    payload.get(
                        "authoritative",
                        False,
                    )
                ),
            }
        )

        if len(
            result
        ) >= requested:
            break

    return result


__all__ = [
    "EPISODE_NAMESPACE",
    "EPISODE_SCHEMA",
    "persist_execution_episode",
    "recall_execution_episodes",
    "xerus_status",
]


# SOPHYANE_EPISODE_TO_SPARSE_MEMORY_V1
#
# Preserve the exact existing Xerus episode writer as the
# authoritative evidence path. After a trusted write succeeds,
# derive a separate lossy cognitive projection. Cognitive failure
# must never invalidate or rewrite the raw episode.
_raw_persist_execution_episode = persist_execution_episode


def persist_execution_episode(event):
    result = _raw_persist_execution_episode(
        event
    )

    if not isinstance(
        result,
        dict,
    ):
        return result

    if (
        result.get("ok") is not True
        or result.get("trusted") is not True
    ):
        return result

    enriched = dict(
        result
    )

    try:
        from sophyane.cognitive_memory import (
            consolidate_verified_episode,
        )

        enriched[
            "cognitive_memory"
        ] = consolidate_verified_episode(
            event
        )

    except Exception as exc:
        enriched[
            "cognitive_memory"
        ] = {
            "ok": False,
            "reason": (
                "cognitive consolidation unavailable: "
                + type(exc).__name__
                + ": "
                + str(exc)
            ),
        }

    return enriched
