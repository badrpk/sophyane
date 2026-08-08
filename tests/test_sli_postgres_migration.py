from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import uuid

import psycopg
from psycopg import sql

from sophyane import sli
from sophyane.sli_migrate_postgres import (
    migrate,
    sqlite_snapshot,
)
from sophyane.sli_postgres import (
    PostgresSLIStore,
)


def _drop_schema(
    dsn: str,
    schema: str,
) -> None:
    with psycopg.connect(
        dsn
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL(
                    "DROP SCHEMA IF EXISTS {} CASCADE"
                ).format(
                    sql.Identifier(
                        schema
                    )
                )
            )


def _source_database(
    path: Path,
) -> None:
    db = sli.connect(
        path
    )

    try:
        first = sli.record(
            db,
            request="make calculator",
            state="empty workspace",
            action="GENERATE_BROWSER_ARTIFACT",
            result="verified",
            reward=1.0,
            confidence=0.95,
            elapsed_seconds=1.25,
            source_type="execution",
        )

        second = sli.record(
            db,
            request="inspect calculator",
            state="index exists",
            action="INSPECT_EVIDENCE",
            result="valid",
            reward=0.5,
            confidence=0.75,
            elapsed_seconds=0.5,
            source_type="validator",
        )

        assert first == 1
        assert second == 2

        sli.store_trace(
            db,
            {
                "trace_id":
                    "trace-001",

                "request":
                    "make calculator",

                "action":
                    "GENERATE_BROWSER_ARTIFACT",

                "status":
                    "succeeded",

                "reward":
                    1.0,

                "quality_reward":
                    0.8,

                "failure_category":
                    "",

                "quality_signals":
                    [
                        "validation_passed:+0.20",
                    ],

                "result":
                    "verified",

                "elapsed_seconds":
                    1.25,

                "workspace_before":
                    {
                        "sample": [],
                    },

                "workspace_after":
                    {
                        "sample": [
                            {
                                "path":
                                    "index.html",

                                "bytes":
                                    123,
                            },
                        ],
                    },
            },
        )

    finally:
        db.close()


def test_sqlite_to_postgres_migration_is_exact_and_idempotent(
    tmp_path: Path,
) -> None:
    dsn = os.environ[
        "SOPHYANE_POSTGRES_DSN"
    ]

    schema = (
        "sli_phase2g_"
        + uuid.uuid4().hex[:16]
    )

    sqlite_path = (
        tmp_path
        / "source.db"
    )

    _source_database(
        sqlite_path
    )

    source = sqlite_snapshot(
        sqlite_path
    )

    store = PostgresSLIStore(
        dsn,
        schema=schema,
    )

    try:
        first = migrate(
            sqlite_path=sqlite_path,
            store=store,
        )

        assert first[
            "equivalent"
        ] is True

        assert first[
            "source_digest"
        ] == first[
            "target_digest"
        ]

        assert first[
            "source_memories"
        ] == 2

        assert first[
            "target_memories"
        ] == 2

        assert first[
            "source_traces"
        ] == 1

        assert first[
            "target_traces"
        ] == 1

        second = migrate(
            sqlite_path=sqlite_path,
            store=store,
        )

        assert second[
            "equivalent"
        ] is True

        assert second[
            "source_digest"
        ] == second[
            "target_digest"
        ]

        target = store.export_snapshot()

        assert target == source

        new_id = store.record(
            request="post migration write",
            action="TEST",
            reward=1.0,
            source_type="execution",
        )

        assert new_id == 3

    finally:
        _drop_schema(
            dsn,
            schema,
        )


def test_migration_cli_refuses_production_schema() -> None:
    from sophyane.sli_migrate_postgres import (
        main,
    )

    try:
        main(
            [
                "--schema",
                "sli",
            ]
        )

    except SystemExit as error:
        assert (
            "Refusing production schema"
            in str(
                error
            )
        )

    else:
        raise AssertionError(
            "production schema was not refused"
        )
