"""Fail-safe durable memory facade for Sophyane.

Filesystem journal is authoritative fallback.
PostgreSQL/pgvector is the durable searchable mirror.
A database failure must never break the harness.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()


def _root() -> Path:
    return Path(
        os.environ.get(
            "SOPHYANE_HOME",
            Path.home() / ".local/share/sophyane",
        )
    ).expanduser()


def _journal() -> Path:
    return _root() / "durable-memory.jsonl"


def _make_key(
    *,
    namespace: str,
    content: str,
    metadata: dict[str, Any],
) -> str:
    payload = (
        namespace
        + "\0"
        + content
        + "\0"
        + json.dumps(
            metadata,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
    )

    return hashlib.sha256(
        payload.encode(
            "utf-8",
            errors="replace",
        )
    ).hexdigest()[:32]


def remember(
    content: str,
    *,
    namespace: str = "general",
    memory_key: str | None = None,
    metadata: dict[str, Any] | None = None,
    embedding: list[float] | None = None,
) -> dict[str, Any]:
    value = str(content or "").strip()

    if not value:
        return {
            "ok": False,
            "reason": "empty content",
        }

    namespace = (
        str(namespace or "").strip()
        or "general"
    )

    metadata_value = dict(
        metadata or {}
    )

    key = (
        str(memory_key).strip()
        if memory_key
        else _make_key(
            namespace=namespace,
            content=value,
            metadata=metadata_value,
        )
    )

    record = {
        "ts": time.time(),
        "memory_key": key,
        "namespace": namespace,
        "content": value,
        "metadata": metadata_value,
    }

    filesystem_ok = False

    with _LOCK:
        try:
            journal = _journal()

            journal.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            with journal.open(
                "a",
                encoding="utf-8",
            ) as handle:
                handle.write(
                    json.dumps(
                        record,
                        ensure_ascii=False,
                        default=str,
                    )
                    + "\n"
                )

            filesystem_ok = True

        except Exception:
            filesystem_ok = False

    postgres_ok = False
    postgres_error = ""

    try:
        from sophyane.postgres_memory import (
            get_postgres_memory,
        )

        memory = get_postgres_memory()

        memory.ensure_schema()

        memory.remember(
            memory_key=key,
            namespace=namespace,
            content=value,
            metadata=metadata_value,
            embedding=embedding,
        )

        postgres_ok = True

    except Exception as exc:
        postgres_error = str(exc)

    return {
        "ok": bool(
            filesystem_ok
            or postgres_ok
        ),
        "memory_key": key,
        "filesystem": filesystem_ok,
        "postgres": postgres_ok,
        "postgres_error": postgres_error,
    }


def remember_event(
    event: str,
    payload: dict[str, Any],
    *,
    namespace: str,
) -> dict[str, Any]:
    event_name = (
        str(event or "").strip()
        or "event"
    )

    return remember(
        (
            event_name
            + ": "
            + json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
        ),
        namespace=namespace,
        metadata={
            "event": event_name,
            "payload": payload,
        },
    )



def remember_verified_execution(event: dict[str, Any]) -> dict[str, Any]:
    """Store a compact episodic projection of one trusted execution event."""
    if not isinstance(event, dict):
        return {"ok": False, "reason": "invalid event"}
    status = str(event.get("status") or "").casefold()
    evidence = event.get("verification_evidence")
    if (
        event.get("accepted") is not True
        or status not in {"success", "succeeded", "completed"}
        or str(event.get("verification_state") or "").casefold() != "verified"
        or not isinstance(evidence, (list, dict))
        or not evidence
    ):
        return {"ok": False, "reason": "event is not trusted verified success"}
    event_key = str(event.get("event_key") or "").strip()
    if not event_key:
        return {"ok": False, "reason": "missing event identity"}
    memory_key = "verified-execution:" + event_key
    journal = _journal()
    try:
        if journal.exists():
            for line in journal.read_text(encoding="utf-8", errors="replace").splitlines()[-5000:]:
                try:
                    prior = json.loads(line)
                except Exception:
                    continue
                if isinstance(prior, dict) and prior.get("memory_key") == memory_key:
                    return {"ok": True, "memory_key": memory_key, "deduplicated": True}
    except Exception:
        pass
    objective = str(event.get("original_objective") or "").strip()
    summary = "Verified execution: " + objective[:1200]
    metadata = {
        "verified_provenance": {
            key: event.get(key)
            for key in (
                "event_key", "objective_hash", "original_objective", "repository_identity",
                "provider_identity", "capability_class", "status", "verification_state",
                "verification_evidence", "accepted", "artifact_paths", "changed_paths",
                "result", "reward", "trace_id", "created_at",
            )
            if key in event
        },
    }
    return remember(
        summary,
        namespace="verified-execution",
        memory_key=memory_key,
        metadata=metadata,
    )

def _postgres_recall(
    query: str,
    *,
    namespace: str | None,
    limit: int,
    repository_identity: str | None = None,
    capability_class: str | None = None,
) -> list[dict[str, Any]]:
    from sophyane.postgres_memory import (
        get_postgres_memory,
    )

    hits = get_postgres_memory().search(
        query,
        namespace=namespace,
        limit=limit,
    )

    records = [
        {
            "memory_key": hit.memory_key,
            "namespace": hit.namespace,
            "content": hit.content,
            "metadata": hit.metadata,
            "distance": hit.distance,
            "source": "postgres-pgvector",
        }
        for hit in hits
    ]
    records.sort(
        key=lambda item: (
            float(item.get("distance", 0.0) or 0.0)
            - _episodic_provenance_bonus(
                item,
                repository_identity=repository_identity,
                capability_class=capability_class,
            ),
            str(item.get("memory_key") or ""),
        )
    )
    return records


def _episodic_provenance_bonus(
    item: dict[str, Any],
    *,
    repository_identity: str | None = None,
    capability_class: str | None = None,
) -> float:
    """Return one small bonus for canonical verified execution evidence."""
    metadata = item.get("metadata")
    if not isinstance(metadata, dict):
        return 0.0
    provenance = metadata.get("verified_provenance")
    if not isinstance(provenance, dict):
        return 0.0
    if provenance.get("accepted") is not True:
        return 0.0
    if str(provenance.get("verification_state") or "").casefold() != "verified":
        return 0.0
    scoped_repo = str(provenance.get("repository_identity") or "").strip().casefold()
    requested_repo = str(repository_identity or "").strip().casefold()
    if scoped_repo and (not requested_repo or scoped_repo != requested_repo):
        return 0.0
    scoped_capability = str(provenance.get("capability_class") or "").strip().casefold()
    requested_capability = str(capability_class or "").strip().casefold()
    if scoped_capability and requested_capability and scoped_capability != requested_capability:
        return 0.0
    if scoped_capability and not requested_capability:
        return 0.0
    return 0.25


def _filesystem_recall(
    query: str,
    *,
    namespace: str | None,
    limit: int,
    repository_identity: str | None = None,
    capability_class: str | None = None,
) -> list[dict[str, Any]]:
    journal = _journal()

    if not journal.exists():
        return []

    query_terms = {
        item.casefold()
        for item in str(query).split()
        if item.strip()
    }

    scored: list[
        tuple[int, float, dict[str, Any]]
    ] = []

    try:
        lines = journal.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()

    except Exception:
        return []

    # Match PostgreSQL upsert semantics in fallback mode:
    # for repeated memory_key values, the latest journal
    # occurrence is authoritative.
    latest_by_key: dict[
        str,
        dict[str, Any],
    ] = {}

    anonymous: list[
        dict[str, Any]
    ] = []

    # Bound local fallback cost.
    for line in lines[-5000:]:
        try:
            item = json.loads(line)
        except Exception:
            continue

        if not isinstance(
            item,
            dict,
        ):
            continue

        key = str(
            item.get(
                "memory_key",
                "",
            )
            or ""
        ).strip()

        if key:
            latest_by_key[key] = item
        else:
            anonymous.append(item)

    candidates = (
        list(latest_by_key.values())
        + anonymous
    )

    for item in candidates:
        if (
            namespace
            and item.get("namespace")
            != namespace
        ):
            continue

        content = str(
            item.get(
                "content",
                "",
            )
        )

        lowered = content.casefold()

        score = sum(
            1
            for term in query_terms
            if term in lowered
        )

        if not score:
            continue

        item = {
            **item,
            "source": "filesystem-journal",
        }
        score = score + _episodic_provenance_bonus(
            item,
            repository_identity=repository_identity,
            capability_class=capability_class,
        )
        scored.append(
            (
                score,
                float(
                    item.get(
                        "ts",
                        0.0,
                    )
                    or 0.0
                ),
                item,
            )
        )

    scored.sort(
        key=lambda item: (
            item[0],
            item[1],
            str(item[2].get("memory_key") or ""),
        ),
        reverse=True,
    )

    return [
        item
        for _, _, item in scored[:limit]
    ]


def recall(
    query: str,
    *,
    namespace: str | None = None,
    limit: int = 8,
    repository_identity: str | None = None,
    capability_class: str | None = None,
) -> list[dict[str, Any]]:
    limit = max(
        1,
        min(
            int(limit),
            50,
        ),
    )

    try:
        hits = _postgres_recall(
            query,
            namespace=namespace,
            limit=limit,
            repository_identity=repository_identity,
            capability_class=capability_class,
        )

        if hits:
            return hits

    except Exception:
        pass

    return _filesystem_recall(
        query,
        namespace=namespace,
        limit=limit,
        repository_identity=repository_identity,
        capability_class=capability_class,
    )


def status() -> dict[str, Any]:
    journal = _journal()

    filesystem = {
        "ok": True,
        "path": str(journal),
        "exists": journal.exists(),
        "bytes": (
            journal.stat().st_size
            if journal.exists()
            else 0
        ),
    }

    try:
        from sophyane.postgres_memory import (
            get_postgres_memory,
        )

        postgres = (
            get_postgres_memory()
            .health()
        )

    except Exception as exc:
        postgres = {
            "ok": False,
            "backend": "postgres-pgvector",
            "error": str(exc),
        }

    return {
        "filesystem": filesystem,
        "postgres": postgres,
        "fallback_enabled": True,
    }
