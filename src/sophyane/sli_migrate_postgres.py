"""Deterministic SQLite -> PostgreSQL migration for Sophyane SLI.

This module does not select the runtime backend and does not perform
automatic production cutover.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from sophyane import sli
from sophyane.sli_postgres import (
    PostgresSLIStore,
)


def _canonical_json(
    value: Any,
) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
        ensure_ascii=False,
    ).encode(
        "utf-8"
    )


def sqlite_snapshot(
    path: Path | str,
) -> dict[str, list[dict[str, Any]]]:
    target = Path(
        path
    ).expanduser()

    db = sqlite3.connect(
        (
            "file:"
            + str(
                target.resolve()
            )
            + "?mode=ro"
        ),
        uri=True,
    )

    db.row_factory = sqlite3.Row

    try:
        integrity = db.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        if integrity != "ok":
            raise RuntimeError(
                "SQLite integrity check failed: "
                + str(
                    integrity
                )
            )

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
        db.close()

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


def snapshot_digest(
    snapshot: dict[
        str,
        list[
            dict[
                str,
                Any,
            ]
        ],
    ],
) -> str:
    digest = hashlib.sha256()

    for table in (
        "memories",
        "traces",
    ):
        for row in snapshot[
            table
        ]:
            digest.update(
                _canonical_json(
                    {
                        "table":
                            table,

                        "row":
                            row,
                    }
                )
            )

            digest.update(
                b"\n"
            )

    return digest.hexdigest()


def verify_snapshots(
    source: dict[
        str,
        list[
            dict[
                str,
                Any,
            ]
        ],
    ],
    target: dict[
        str,
        list[
            dict[
                str,
                Any,
            ]
        ],
    ],
) -> dict[str, Any]:
    source_digest = snapshot_digest(
        source
    )

    target_digest = snapshot_digest(
        target
    )

    equivalent = (
        source
        == target
    )

    return {
        "equivalent":
            equivalent,

        "source_digest":
            source_digest,

        "target_digest":
            target_digest,

        "source_memories":
            len(
                source[
                    "memories"
                ]
            ),

        "target_memories":
            len(
                target[
                    "memories"
                ]
            ),

        "source_traces":
            len(
                source[
                    "traces"
                ]
            ),

        "target_traces":
            len(
                target[
                    "traces"
                ]
            ),
    }


def migrate(
    *,
    sqlite_path: Path | str,
    store: PostgresSLIStore,
) -> dict[str, Any]:
    source = sqlite_snapshot(
        sqlite_path
    )

    store.ensure_schema()

    for memory in source[
        "memories"
    ]:
        store.import_memory(
            memory
        )

    store.synchronize_memory_identity()

    for trace in source[
        "traces"
    ]:
        store.store_trace(
            trace
        )

    target = store.export_snapshot()

    verification = verify_snapshots(
        source,
        target,
    )

    if not verification[
        "equivalent"
    ]:
        raise RuntimeError(
            "SQLite/PostgreSQL SLI migration "
            "verification failed: "
            + json.dumps(
                verification,
                sort_keys=True,
            )
        )

    return verification


def main(
    argv: list[str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog=(
            "sophyane-sli-migrate-postgres"
        ),
    )

    parser.add_argument(
        "--sqlite",
        default=str(
            sli.DB_PATH
        ),
    )

    parser.add_argument(
        "--schema",
        required=True,
    )

    args = parser.parse_args(
        argv
    )

    if args.schema == "sli":
        raise SystemExit(
            "Refusing production schema 'sli' "
            "during migration preparation."
        )

    store = PostgresSLIStore(
        schema=args.schema,
    )

    result = migrate(
        sqlite_path=args.sqlite,
        store=store,
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
