"""Convert execution traces into source-aware SLI memories."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time

from typing import Any

from sophyane import sli_backend as sli


BROWSER_TERMS = (
    "calculator", "game", "dashboard", "website", "webpage", "html",
    "form", "quiz", "clock", "timer", "converter", "todo", "portfolio",
    "responsive", "mobile app",
)

FAILURE_PATTERNS = (
    ("EMPTY_PROVIDER_RESPONSE", ("empty provider response", "returned no text")),
    ("UNUSABLE_PROVIDER_RESPONSE", ("could not produce a usable artifact", "no usable artifact")),
    ("INVALID_PLAN_SCHEMA", ("invalid schema", "malformed json", "json decode")),
    ("NO_ACTION_RETURNED", ("no action", "premature completion")),
    ("ARTIFACT_VALIDATION_FAILED", ("validation failed", "structural verification failed", "html rejected")),
    ("EXECUTION_ERROR", ("execution error", "command failed", "traceback")),
    ("BOUNDED_REPAIR_EXHAUSTED", ("bounded repair", "stopped after bounded")),
)


def classify_action(request: object) -> str:
    text = str(request or "").lower()
    if any(term in text for term in BROWSER_TERMS):
        return "GENERATE_BROWSER_ARTIFACT"
    return "EXECUTE_STRUCTURED_TASK"


def classify_failure(status: object, result: object, error: object = "") -> str:
    if str(status or "").lower() in {"success", "succeeded", "completed"}:
        return ""
    evidence = f"{result}\n{error}".lower()
    for category, patterns in FAILURE_PATTERNS:
        if any(pattern in evidence for pattern in patterns):
            return category
    return "UNKNOWN_FAILURE"


def _paths(snapshot: object) -> set[str]:
    """Return artifact paths from supported execution-snapshot shapes."""
    if not isinstance(snapshot, dict):
        return set()

    paths: set[str] = set()

    # Canonical structured snapshot used by SLI training/evaluation:
    #
    # {
    #     "files": ...,
    #     "bytes": ...,
    #     "sample": [
    #         {"path": "index.html", "bytes": ...},
    #     ],
    # }
    sample = snapshot.get("sample", [])

    if isinstance(sample, (list, tuple)):
        for item in sample:
            value = (
                item.get("path", "")
                if isinstance(item, dict)
                else item
            )

            if str(value).strip():
                paths.add(
                    str(value).strip().lower()
                )

    # Compatibility with execution-runtime snapshots that map relative
    # artifact paths directly to hashes or other fingerprints:
    #
    # {
    #     "index.html": "<sha256>",
    #     "src/app.py": "<sha256>",
    # }
    metadata_keys = {
        "files",
        "bytes",
        "sample",
    }

    for key in snapshot:
        value = str(key).strip()

        if (
            value
            and value.lower() not in metadata_keys
        ):
            paths.add(
                value.lower()
            )

    return paths


def calculate_quality_reward(
    *,
    status: object,
    result: object,
    error: object = "",
    workspace_before: object = None,
    workspace_after: object = None,
) -> tuple[float, list[str], str]:
    status_text = str(status or "").lower()
    evidence = f"{result}\n{error}".lower()
    new_paths = _paths(workspace_after) - _paths(workspace_before)
    signals: list[str] = []

    if status_text in {"success", "succeeded", "completed"}:
        reward = 0.35
        signals.append("successful_status:+0.35")
        browser_artifact = any(
            path.endswith((".html", ".htm", ".css", ".js", ".jsx", ".tsx", ".vue", ".svelte"))
            for path in (new_paths or _paths(workspace_after))
        )
        if browser_artifact:
            reward += 0.20
            signals.append("artifact_created:+0.20")
        if any(marker in evidence for marker in (
            "passed structural verification",
            "validation passed",
            "validation: passed",
            "final validation: passed",
            "strict behavioral validation: passed",
            "verified current workspace page",
            "browser artifact passed",
        )):
            reward += 0.20
            signals.append("validation_passed:+0.20")
        if any(marker in evidence for marker in (
            "opening verified browser preview", "served over http",
            "project completed successfully", "http/1.1\" 200",
        )):
            reward += 0.15
            signals.append("runtime_delivery_verified:+0.15")
        if not any(marker in evidence for marker in (
            "traceback", "runtime error", "validation failed", "command failed",
        )):
            reward += 0.10
            signals.append("no_detected_runtime_error:+0.10")
        category = ""
    else:
        reward = -0.35
        signals.append("failed_status:-0.35")
        category = classify_failure(status, result, error)
        penalty = {
            "EMPTY_PROVIDER_RESPONSE": -0.25,
            "UNUSABLE_PROVIDER_RESPONSE": -0.25,
            "INVALID_PLAN_SCHEMA": -0.20,
            "NO_ACTION_RETURNED": -0.20,
            "ARTIFACT_VALIDATION_FAILED": -0.30,
            "EXECUTION_ERROR": -0.35,
            "BOUNDED_REPAIR_EXHAUSTED": -0.15,
            "UNKNOWN_FAILURE": -0.10,
        }.get(category, -0.10)
        reward += penalty
        signals.append(f"{category.lower()}:{penalty:+.2f}")
        if any(marker in evidence for marker in (
            "previous working files were preserved", "stopped safely",
            "execution stopped safely",
        )):
            reward += 0.10
            signals.append("safe_failure_preservation:+0.10")
        if new_paths:
            reward += 0.05
            signals.append("partial_artifact_preserved:+0.05")

    return max(-1.0, min(1.0, reward)), signals, category


def _learner_event_digest(
    payload: dict[str, Any],
) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode(
        "utf-8"
    )

    return hashlib.sha256(
        encoded
    ).hexdigest()


def _canonical_provenance(
    *,
    request: str,
    workspace_after: dict[str, Any],
    status: str,
    provenance: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Normalize one execution event without inventing evidence."""
    if not isinstance(provenance, dict):
        return None
    event = dict(provenance)
    event.setdefault("original_objective", request)
    event.setdefault(
        "objective_hash",
        hashlib.sha256(str(event["original_objective"]).encode("utf-8")).hexdigest(),
    )
    event.setdefault("status", status)
    event.setdefault("workspace", "")
    event.setdefault("changed_paths", [])
    event.setdefault("artifact_paths", [])
    event.setdefault("repository_identity", None)
    event.setdefault("provider_identity", None)
    event.setdefault("capability_class", None)
    event.setdefault("verification_evidence", [])
    event.setdefault("verification_state", "unverified")
    event["accepted"] = bool(
        event.get("accepted")
        and str(event.get("status") or status).lower() in {"success", "succeeded", "completed"}
        and str(event.get("verification_state") or "").lower() == "verified"
    )
    event.setdefault("result", "")
    event.setdefault("reward", 1.0 if event["accepted"] else 0.0)
    event.setdefault("trace_id", "")
    event.setdefault("created_at", time.time())
    event["event_key"] = _learner_event_digest({
        "objective_hash": event.get("objective_hash"),
        "status": event.get("status"),
        "workspace_after": workspace_after,
    })
    return event


def _ensure_provenance_columns(db: object) -> bool:
    """Add backward-compatible SQLite columns when the legacy schema exists."""
    if not isinstance(db, sqlite3.Connection):
        return False
    columns = {str(row[1]) for row in db.execute("PRAGMA table_info(learned_execution_traces)").fetchall()}
    if "provenance_json" not in columns:
        db.execute("ALTER TABLE learned_execution_traces ADD COLUMN provenance_json TEXT NOT NULL DEFAULT '{}'")
    if "event_key" not in columns:
        db.execute("ALTER TABLE learned_execution_traces ADD COLUMN event_key TEXT NOT NULL DEFAULT ''")
    db.commit()
    return True


def read_verified_history(
    *,
    request: str = "",
    objective_hash: str | None = None,
    repository_identity: str | None = None,
    capability_class: str | None = None,
    provider_identity: str | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Read bounded, canonical trusted-success provenance without side effects."""
    from sophyane import sli as sqlite_sli

    path = sqlite_sli.DB_PATH
    if not path.exists():
        return []
    bounded_limit = max(1, min(int(limit), 16))
    try:
        with sqlite3.connect(path) as db:
            columns = {
                str(row[1])
                for row in db.execute(
                    "PRAGMA table_info(learned_execution_traces)"
                ).fetchall()
            }
            if "provenance_json" not in columns:
                return []
            rows = db.execute(
                "SELECT provenance_json FROM learned_execution_traces "
                "WHERE provenance_json LIKE ? AND provenance_json LIKE ? "
                "ORDER BY created_at DESC LIMIT ?",
                ('%"accepted":true%', '%"verification_state":"verified"%', bounded_limit * 8),
            ).fetchall()
    except (OSError, sqlite3.Error):
        return []

    requested = {
        "repository_identity": str(repository_identity or "").casefold(),
        "capability_class": str(capability_class or "").casefold(),
        "provider_identity": str(provider_identity or "").casefold(),
        "objective_hash": str(objective_hash or "").strip(),
    }
    records: list[dict[str, Any]] = []
    for row in rows:
        try:
            record = json.loads(str(row[0] or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict):
            continue
        if record.get("accepted") is not True:
            continue
        if str(record.get("verification_state") or "").casefold() != "verified":
            continue
        if str(record.get("status") or "").casefold() not in {"success", "succeeded", "completed"}:
            continue
        if requested["objective_hash"] and record.get("objective_hash") != requested["objective_hash"]:
            continue
        if (
            str(request or "").strip()
            and not requested["objective_hash"]
            and not any(
                requested[key]
                for key in ("repository_identity", "capability_class", "provider_identity")
            )
            and _similarity(request, record.get("original_objective", "")) <= 0.0
        ):
            continue
        identity_match = any(
            requested[key] and str(record.get(key) or "").casefold() == requested[key]
            for key in ("repository_identity", "capability_class", "provider_identity")
        )
        if any(requested[key] for key in ("repository_identity", "capability_class", "provider_identity")) and not identity_match:
            continue
        records.append(record)
        if len(records) >= bounded_limit:
            break
    return records


def learn_execution(
    *,
    trace_id: str,
    request: str,
    workspace_before: dict[str, Any],
    workspace_after: dict[str, Any],
    status: str,
    reward: float,
    result: str,
    elapsed_seconds: float,
    error: str = "",
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del reward  # quality is derived from validator evidence, not caller claims.

    canonical_provenance = _canonical_provenance(
        request=request,
        workspace_after=workspace_after,
        status=status,
        provenance=provenance,
    )
    event_key = _learner_event_digest({
        "objective_hash": (
            canonical_provenance.get("objective_hash")
            if canonical_provenance is not None
            else hashlib.sha256(request.encode("utf-8")).hexdigest()
        ),
        "status": status,
        "workspace_after": workspace_after,
    })

    action = classify_action(
        request
    )

    (
        quality_reward,
        quality_signals,
        failure_category,
    ) = calculate_quality_reward(
        status=status,
        result=result,
        error=error,
        workspace_before=workspace_before,
        workspace_after=workspace_after,
    )

    confidence = (
        1.0
        if status.lower()
        in {
            "success",
            "succeeded",
            "completed",
        }
        else 0.8
    )

    trace_payload = {
        "trace_id":
            trace_id,

        "request":
            request,

        "action":
            action,

        "status":
            status,

        "reward":
            quality_reward,

        "quality_reward":
            quality_reward,

        "failure_category":
            failure_category,

        "quality_signals":
            quality_signals,

        "result":
            result,

        "elapsed_seconds":
            elapsed_seconds,

        "workspace_before":
            workspace_before,

        "workspace_after":
            workspace_after,
    }

    mirror_result = None
    atomic_result = None

    with sli.connect() as db:
        sqlite_provenance = _ensure_provenance_columns(db)

        # The race producer and compatibility callers may observe one execution.
        if sqlite_provenance:
            existing = db.execute(
                "SELECT trace_id FROM learned_execution_traces "
                "WHERE event_key = ? AND provenance_json LIKE ? "
                "ORDER BY created_at LIMIT 1",
                (event_key, '%"accepted":true%'),
            ).fetchone()
            if existing is not None:
                return {
                    "memory_id": 0,
                    "trace_id": str(existing[0]),
                    "action": action,
                    "quality_reward": quality_reward,
                    "quality_signals": quality_signals,
                    "failure_category": failure_category,
                    "provenance": canonical_provenance,
                    "deduplicated": True,
                }

        use_atomic_postgres = (
            sli.selected_backend()
            == "postgres"
            and sli.atomic_learning_enabled()
        )

        if use_atomic_postgres:
            canonical_payload = {
                "trace_id":
                    trace_id,

                "request":
                    request,

                "action":
                    action,

                "status":
                    status,

                "quality_reward":
                    quality_reward,

                "failure_category":
                    failure_category,

                "quality_signals":
                    quality_signals,

                "result":
                    result,

                "elapsed_seconds":
                    elapsed_seconds,

                "workspace_before":
                    workspace_before,

                "workspace_after":
                    workspace_after,
            }

            payload_digest = (
                _learner_event_digest(
                    canonical_payload
                )
            )

            atomic_result = (
                sli.atomic_learn_execution(
                    db,

                    trace_id=trace_id,

                    payload_digest=
                        payload_digest,

                    memory={
                        "request":
                            request,

                        "state":
                            "execution completed",

                        "action":
                            action,

                        "result":
                            result,

                        "reward":
                            quality_reward,

                        "confidence":
                            confidence,

                        "elapsed_seconds":
                            elapsed_seconds,

                        "source_type":
                            "execution",
                    },

                    trace={**trace_payload, "provenance": canonical_provenance},
                )
            )

            memory_id = int(
                atomic_result[
                    "memory_id"
                ]
            )

        else:
            memory_id = sli.record(
                db,
                request=request,
                state="execution completed",
                action=action,
                result=result,
                reward=quality_reward,
                confidence=confidence,
                elapsed_seconds=elapsed_seconds,
                source_type="execution",
            )

            sli.store_trace(
                db,
                trace_payload,
            )

        if sqlite_provenance and canonical_provenance is not None:
            db.execute(
                "UPDATE learned_execution_traces SET provenance_json = ?, event_key = ? WHERE trace_id = ?",
                (
                    json.dumps(canonical_provenance, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
                    canonical_provenance["event_key"],
                    trace_id,
                ),
            )
            db.commit()

    promotion_result = None
    if (
        canonical_provenance is not None
        and canonical_provenance.get("accepted") is True
        and (
            canonical_provenance.get("artifact_paths")
            or canonical_provenance.get("changed_paths")
        )
    ):
        try:
            from sophyane.code_memory.promote_success import promote_workspace

            promotion_result = promote_workspace(
                canonical_provenance.get("workspace") or "",
                request=request,
                source="promote:verified-execution",
                report="success: true\nvalidation: passed",
                paths=(
                    canonical_provenance.get("artifact_paths")
                    or canonical_provenance.get("changed_paths")
                ),
                provenance=canonical_provenance,
            )
        except Exception as exc:
            promotion_result = {
                "ok": False,
                "reason": f"promotion unavailable: {type(exc).__name__}: {exc}",
                "chunks_added": 0,
            }

    # PostgreSQL writes are not fully durable for rollback purposes until
    # SQLite catches up. This is intentionally retried even when the atomic
    # event already existed, because a prior attempt may have failed only
    # during rollback-mirror synchronization.
    mirror_result = (
        sli.synchronize_rollback_mirror()
    )

    response = {
        "memory_id":
            memory_id,

        "trace_id":
            trace_id,

        "action":
            action,

        "quality_reward":
            quality_reward,

        "quality_signals":
            quality_signals,

        "failure_category":
            failure_category,

        "rollback_mirror":
            mirror_result,
    }

    if canonical_provenance is not None:
        response["provenance"] = canonical_provenance
    if promotion_result is not None:
        response["promotion"] = promotion_result

    if atomic_result is not None:
        response[
            "atomic_learning"
        ] = {
            "state":
                atomic_result[
                    "state"
                ],

            "created":
                bool(
                    atomic_result[
                        "created"
                    ]
                ),

            "payload_digest":
                atomic_result[
                    "payload_digest"
                ],
        }

    return response
