"""Controlled PostgreSQL production preparation for Sophyane SLI.

This module can create, verify and roll back the production PostgreSQL
SLI schema. It intentionally does not select PostgreSQL as the runtime
backend.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from sophyane import sli
from sophyane.sli_migrate_postgres import (
    migrate,
    sqlite_snapshot,
    snapshot_digest,
    verify_snapshots,
)
from sophyane.sli_postgres import (
    PostgresSLIStore,
)


PRODUCTION_SCHEMA = "sli"

STATE_DIR = (
    Path.home()
    / ".local/state/sophyane"
)

CUTOVER_STATE = (
    STATE_DIR
    / "sli-postgres-cutover.json"
)


def _write_manifest(
    payload: dict[str, Any],
) -> None:
    STATE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    CUTOVER_STATE.write_text(
        json.dumps(
            payload,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _read_manifest() -> dict[str, Any] | None:
    if not CUTOVER_STATE.is_file():
        return None

    return json.loads(
        CUTOVER_STATE.read_text(
            encoding="utf-8"
        )
    )


def source_fingerprint(
    sqlite_path: Path | str = sli.DB_PATH,
) -> dict[str, Any]:
    snapshot = sqlite_snapshot(
        sqlite_path
    )

    return {
        "sqlite":
            str(
                Path(
                    sqlite_path
                ).expanduser()
            ),

        "digest":
            snapshot_digest(
                snapshot
            ),

        "memories":
            len(
                snapshot[
                    "memories"
                ]
            ),

        "traces":
            len(
                snapshot[
                    "traces"
                ]
            ),
    }


def prepare(
    *,
    sqlite_path: Path | str = sli.DB_PATH,
    store: PostgresSLIStore | None = None,
) -> dict[str, Any]:
    target = (
        store
        or PostgresSLIStore(
            schema=PRODUCTION_SCHEMA,
        )
    )

    if target.schema != PRODUCTION_SCHEMA:
        raise ValueError(
            "Production prepare requires schema 'sli'."
        )

    if target.schema_exists():
        raise RuntimeError(
            "Production PostgreSQL SLI schema already exists. "
            "Refusing destructive overwrite."
        )

    source = sqlite_snapshot(
        sqlite_path
    )

    source_digest = snapshot_digest(
        source
    )

    verification = migrate(
        sqlite_path=sqlite_path,
        store=target,
    )

    if not verification[
        "equivalent"
    ]:
        target.drop_schema()

        raise RuntimeError(
            "Production SLI migration failed verification."
        )

    manifest = {
        "state":
            "prepared",

        "schema":
            PRODUCTION_SCHEMA,

        "sqlite_path":
            str(
                Path(
                    sqlite_path
                ).expanduser()
            ),

        "source_digest":
            source_digest,

        "target_digest":
            verification[
                "target_digest"
            ],

        "memories":
            verification[
                "target_memories"
            ],

        "traces":
            verification[
                "target_traces"
            ],

        "runtime_backend":
            "sqlite",
    }

    _write_manifest(
        manifest
    )

    return manifest


def verify(
    *,
    sqlite_path: Path | str = sli.DB_PATH,
    store: PostgresSLIStore | None = None,
) -> dict[str, Any]:
    target = (
        store
        or PostgresSLIStore(
            schema=PRODUCTION_SCHEMA,
        )
    )

    if not target.schema_exists():
        raise RuntimeError(
            "Production PostgreSQL SLI schema does not exist."
        )

    source = sqlite_snapshot(
        sqlite_path
    )

    target_snapshot = target.export_snapshot()

    verification = verify_snapshots(
        source,
        target_snapshot,
    )

    if not verification[
        "equivalent"
    ]:
        raise RuntimeError(
            "Production PostgreSQL SLI differs from SQLite source: "
            + json.dumps(
                verification,
                sort_keys=True,
            )
        )

    manifest = _read_manifest()

    return {
        **verification,

        "schema":
            PRODUCTION_SCHEMA,

        "manifest_present":
            manifest is not None,

        "runtime_backend":
            "sqlite",
    }




def _sqlite_snapshot_connection(
    db: sqlite3.Connection,
) -> dict[str, list[dict[str, Any]]]:
    """Canonical SLI snapshot visible to this SQLite connection.

    Unlike sqlite_snapshot(path), this can see writes made inside the
    caller's still-open transaction.
    """
    old_row_factory = db.row_factory

    db.row_factory = sqlite3.Row

    try:
        memories = [
            dict(
                row
            )
            for row in db.execute(
                """
                SELECT
                    id,
                    request,
                    state,
                    action,
                    result,
                    reward,
                    confidence,
                    elapsed_seconds,
                    source_type,
                    created_at
                FROM memories
                ORDER BY id
                """
            ).fetchall()
        ]

        traces = [
            dict(
                row
            )
            for row in db.execute(
                """
                SELECT
                    trace_id,
                    request,
                    action,
                    status,
                    reward,
                    quality_reward,
                    failure_category,
                    quality_signals,
                    result,
                    elapsed_seconds,
                    workspace_before,
                    workspace_after,
                    created_at
                FROM learned_execution_traces
                ORDER BY trace_id
                """
            ).fetchall()
        ]

    finally:
        db.row_factory = old_row_factory

    for row in traces:
        for key in (
            "quality_signals",
            "workspace_before",
            "workspace_after",
        ):
            value = row.get(
                key
            )

            if isinstance(
                value,
                str,
            ):
                row[
                    key
                ] = json.loads(
                    value
                )

    return {
        "memories":
            memories,

        "traces":
            traces,
    }



def synchronize_postgres_to_sqlite(
    *,
    sqlite_path: Path | str = sli.DB_PATH,
    store: PostgresSLIStore | None = None,
) -> dict[str, Any]:
    """Append PostgreSQL-only SLI learning into SQLite safely.

    Synchronization is intentionally one-way and append-only.

    Existing SQLite rows must already exist identically in PostgreSQL.
    Existing PostgreSQL rows may not conflict with SQLite.
    New memory IDs must form one contiguous sequence immediately after
    the highest SQLite memory ID.

    The SQLite update is transactional and is verified against the full
    PostgreSQL canonical snapshot before returning.
    """
    target = (
        store
        or PostgresSLIStore(
            schema=PRODUCTION_SCHEMA,
        )
    )

    if not target.schema_exists():
        raise RuntimeError(
            "PostgreSQL SLI schema does not exist; "
            "rollback synchronization cannot proceed."
        )

    sqlite_target = Path(
        sqlite_path
    ).expanduser()

    source_before = sqlite_snapshot(
        sqlite_target
    )

    postgres_snapshot = target.export_snapshot()

    sqlite_memories = {
        int(row["id"]):
            row
        for row in source_before[
            "memories"
        ]
    }

    postgres_memories = {
        int(row["id"]):
            row
        for row in postgres_snapshot[
            "memories"
        ]
    }

    sqlite_traces = {
        str(row["trace_id"]):
            row
        for row in source_before[
            "traces"
        ]
    }

    postgres_traces = {
        str(row["trace_id"]):
            row
        for row in postgres_snapshot[
            "traces"
        ]
    }

    missing_postgres_memory_ids = sorted(
        set(
            sqlite_memories
        )
        - set(
            postgres_memories
        )
    )

    if missing_postgres_memory_ids:
        raise RuntimeError(
            "PostgreSQL rollback target is missing existing "
            "SQLite memory IDs: "
            + repr(
                missing_postgres_memory_ids
            )
        )

    conflicting_memory_ids = [
        memory_id
        for memory_id in sorted(
            sqlite_memories
        )
        if (
            sqlite_memories[
                memory_id
            ]
            != postgres_memories[
                memory_id
            ]
        )
    ]

    if conflicting_memory_ids:
        raise RuntimeError(
            "PostgreSQL rollback target conflicts with "
            "existing SQLite memory IDs: "
            + repr(
                conflicting_memory_ids
            )
        )

    missing_postgres_trace_ids = sorted(
        set(
            sqlite_traces
        )
        - set(
            postgres_traces
        )
    )

    if missing_postgres_trace_ids:
        raise RuntimeError(
            "PostgreSQL rollback target is missing existing "
            "SQLite trace IDs: "
            + repr(
                missing_postgres_trace_ids
            )
        )

    conflicting_trace_ids = [
        trace_id
        for trace_id in sorted(
            sqlite_traces
        )
        if (
            sqlite_traces[
                trace_id
            ]
            != postgres_traces[
                trace_id
            ]
        )
    ]

    if conflicting_trace_ids:
        raise RuntimeError(
            "PostgreSQL rollback target conflicts with "
            "existing SQLite trace IDs: "
            + repr(
                conflicting_trace_ids
            )
        )

    new_memory_ids = sorted(
        set(
            postgres_memories
        )
        - set(
            sqlite_memories
        )
    )

    highest_sqlite_id = max(
        sqlite_memories,
        default=0,
    )

    non_append_memory_ids = [
        memory_id
        for memory_id in new_memory_ids
        if memory_id <= highest_sqlite_id
    ]

    if non_append_memory_ids:
        raise RuntimeError(
            "PostgreSQL-only memory IDs are not append-only "
            "after SQLite: "
            f"highest SQLite memory ID is "
            f"{highest_sqlite_id!r}; "
            f"found historical PostgreSQL-only IDs "
            f"{non_append_memory_ids!r}."
        )

    new_trace_ids = sorted(
        set(
            postgres_traces
        )
        - set(
            sqlite_traces
        )
    )

    new_memories = [
        postgres_memories[
            memory_id
        ]
        for memory_id in new_memory_ids
    ]

    new_traces = [
        postgres_traces[
            trace_id
        ]
        for trace_id in new_trace_ids
    ]

    before_digest = snapshot_digest(
        source_before
    )

    target_digest = snapshot_digest(
        postgres_snapshot
    )

    if (
        not new_memories
        and not new_traces
    ):
        if source_before != postgres_snapshot:
            raise RuntimeError(
                "SQLite/PostgreSQL differ but contain no "
                "appendable PostgreSQL-only rows."
            )

        return {
            "state":
                "already_converged",

            "schema":
                target.schema,

            "sqlite_path":
                str(
                    sqlite_target
                ),

            "memories_added":
                0,

            "traces_added":
                0,

            "source_digest_before":
                before_digest,

            "source_digest_after":
                before_digest,

            "target_digest":
                target_digest,

            "memories":
                len(
                    source_before[
                        "memories"
                    ]
                ),

            "traces":
                len(
                    source_before[
                        "traces"
                    ]
                ),

            "runtime_backend":
                "sqlite",
        }

    db = sqlite3.connect(
        sqlite_target
    )

    try:
        db.execute(
            "BEGIN IMMEDIATE"
        )

        for memory in new_memories:
            db.execute(
                """
                INSERT INTO memories (
                    id,
                    request,
                    state,
                    action,
                    result,
                    reward,
                    confidence,
                    elapsed_seconds,
                    source_type,
                    created_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    int(
                        memory[
                            "id"
                        ]
                    ),
                    str(
                        memory[
                            "request"
                        ]
                    ),
                    str(
                        memory.get(
                            "state",
                            "",
                        )
                    ),
                    str(
                        memory[
                            "action"
                        ]
                    ),
                    str(
                        memory.get(
                            "result",
                            "",
                        )
                    ),
                    float(
                        memory.get(
                            "reward",
                            0.0,
                        )
                    ),
                    float(
                        memory.get(
                            "confidence",
                            0.5,
                        )
                    ),
                    float(
                        memory.get(
                            "elapsed_seconds",
                            0.0,
                        )
                    ),
                    str(
                        memory.get(
                            "source_type",
                            "unknown",
                        )
                    ),
                    float(
                        memory[
                            "created_at"
                        ]
                    ),
                ),
            )

        for trace in new_traces:
            db.execute(
                """
                INSERT INTO learned_execution_traces (
                    trace_id,
                    request,
                    action,
                    status,
                    reward,
                    quality_reward,
                    failure_category,
                    quality_signals,
                    result,
                    elapsed_seconds,
                    workspace_before,
                    workspace_after,
                    created_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    str(
                        trace[
                            "trace_id"
                        ]
                    ),
                    str(
                        trace[
                            "request"
                        ]
                    ),
                    str(
                        trace[
                            "action"
                        ]
                    ),
                    str(
                        trace[
                            "status"
                        ]
                    ),
                    float(
                        trace[
                            "reward"
                        ]
                    ),
                    float(
                        trace.get(
                            "quality_reward",
                            0.0,
                        )
                    ),
                    str(
                        trace.get(
                            "failure_category",
                            "",
                        )
                    ),
                    json.dumps(
                        trace.get(
                            "quality_signals",
                            [],
                        ),
                        sort_keys=True,
                        separators=(
                            ",",
                            ":",
                        ),
                        ensure_ascii=False,
                    ),
                    str(
                        trace.get(
                            "result",
                            "",
                        )
                    ),
                    float(
                        trace.get(
                            "elapsed_seconds",
                            0.0,
                        )
                    ),
                    json.dumps(
                        trace.get(
                            "workspace_before",
                            {},
                        ),
                        sort_keys=True,
                        separators=(
                            ",",
                            ":",
                        ),
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        trace.get(
                            "workspace_after",
                            {},
                        ),
                        sort_keys=True,
                        separators=(
                            ",",
                            ":",
                        ),
                        ensure_ascii=False,
                    ),
                    float(
                        trace[
                            "created_at"
                        ]
                    ),
                ),
            )

        after_inside_transaction = _sqlite_snapshot_connection(
            db
        )

        verification = verify_snapshots(
            after_inside_transaction,
            postgres_snapshot,
        )

        if not verification[
            "equivalent"
        ]:
            raise RuntimeError(
                "PostgreSQL -> SQLite rollback "
                "synchronization verification failed: "
                + json.dumps(
                    verification,
                    sort_keys=True,
                )
            )

        db.commit()

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()

    source_after = sqlite_snapshot(
        sqlite_target
    )

    final_verification = verify_snapshots(
        source_after,
        postgres_snapshot,
    )

    if not final_verification[
        "equivalent"
    ]:
        raise RuntimeError(
            "Committed PostgreSQL -> SQLite rollback "
            "synchronization failed final verification: "
            + json.dumps(
                final_verification,
                sort_keys=True,
            )
        )

    return {
        "state":
            "synchronized",

        "schema":
            target.schema,

        "sqlite_path":
            str(
                sqlite_target
            ),

        "memories_added":
            len(
                new_memories
            ),

        "traces_added":
            len(
                new_traces
            ),

        "source_digest_before":
            before_digest,

        "source_digest_after":
            final_verification[
                "source_digest"
            ],

        "target_digest":
            final_verification[
                "target_digest"
            ],

        "memories":
            final_verification[
                "source_memories"
            ],

        "traces":
            final_verification[
                "source_traces"
            ],

        "runtime_backend":
            "sqlite",
    }


def rollback_synchronized(
    *,
    sqlite_path: Path | str = sli.DB_PATH,
    store: PostgresSLIStore | None = None,
) -> dict[str, Any]:
    """Synchronize PostgreSQL-only learning, verify, then drop PostgreSQL."""
    target = (
        store
        or PostgresSLIStore(
            schema=PRODUCTION_SCHEMA,
        )
    )

    synchronization = synchronize_postgres_to_sqlite(
        sqlite_path=sqlite_path,
        store=target,
    )

    source_after_sync = sqlite_snapshot(
        sqlite_path
    )

    postgres_before_drop = target.export_snapshot()

    verification = verify_snapshots(
        source_after_sync,
        postgres_before_drop,
    )

    if not verification[
        "equivalent"
    ]:
        raise RuntimeError(
            "Refusing PostgreSQL rollback because SQLite "
            "has not converged with PostgreSQL."
        )

    target.drop_schema()

    if target.schema_exists():
        raise RuntimeError(
            "PostgreSQL SLI schema still exists after rollback."
        )

    source_after_drop = sqlite_snapshot(
        sqlite_path
    )

    if (
        source_after_drop
        != source_after_sync
    ):
        raise RuntimeError(
            "SQLite changed while PostgreSQL schema was dropped."
        )

    manifest = {
        "state":
            "rolled_back_synchronized",

        "schema":
            target.schema,

        "source_digest":
            snapshot_digest(
                source_after_drop
            ),

        "memories":
            len(
                source_after_drop[
                    "memories"
                ]
            ),

        "traces":
            len(
                source_after_drop[
                    "traces"
                ]
            ),

        "memories_added":
            synchronization[
                "memories_added"
            ],

        "traces_added":
            synchronization[
                "traces_added"
            ],

        "runtime_backend":
            "sqlite",
    }

    _write_manifest(
        manifest
    )

    return manifest


def rollback(
    *,
    sqlite_path: Path | str = sli.DB_PATH,
    store: PostgresSLIStore | None = None,
) -> dict[str, Any]:
    target = (
        store
        or PostgresSLIStore(
            schema=PRODUCTION_SCHEMA,
        )
    )

    source_before = source_fingerprint(
        sqlite_path
    )

    target.drop_schema()

    source_after = source_fingerprint(
        sqlite_path
    )

    if source_before != source_after:
        raise RuntimeError(
            "SQLite source changed during PostgreSQL rollback."
        )

    manifest = {
        "state":
            "rolled_back",

        "schema":
            PRODUCTION_SCHEMA,

        "source_digest":
            source_after[
                "digest"
            ],

        "memories":
            source_after[
                "memories"
            ],

        "traces":
            source_after[
                "traces"
            ],

        "runtime_backend":
            "sqlite",
    }

    _write_manifest(
        manifest
    )

    return manifest


def main(
    argv: list[str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="sophyane-sli-cutover",
    )

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    for name in (
        "prepare",
        "verify",
        "rollback",
        "status",
    ):
        command = sub.add_parser(
            name
        )

        command.add_argument(
            "--sqlite",
            default=str(
                sli.DB_PATH
            ),
        )

    args = parser.parse_args(
        argv
    )

    if args.command == "status":
        print(
            json.dumps(
                {
                    "manifest":
                        _read_manifest(),

                    "production_schema_exists":
                        PostgresSLIStore(
                            schema=PRODUCTION_SCHEMA,
                        ).schema_exists(),

                    "runtime_backend":
                        "sqlite",
                },
                sort_keys=True,
                indent=2,
            )
        )

        return 0

    if args.command == "prepare":
        result = prepare(
            sqlite_path=args.sqlite,
        )

    elif args.command == "verify":
        result = verify(
            sqlite_path=args.sqlite,
        )

    else:
        result = rollback(
            sqlite_path=args.sqlite,
        )

    print(
        json.dumps(
            result,
            sort_keys=True,
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
