from __future__ import annotations

import os
from pathlib import Path
import uuid

import psycopg
from psycopg import sql

from sophyane import sli
import sophyane.sli_cutover as cutover
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


def _source(
    path: Path,
) -> None:
    db = sli.connect(
        path
    )

    try:
        sli.record(
            db,
            request="one",
            action="TEST",
            reward=1.0,
            source_type="execution",
        )

        sli.store_trace(
            db,
            {
                "trace_id":
                    "cutover-trace",

                "request":
                    "one",

                "action":
                    "TEST",

                "status":
                    "succeeded",

                "reward":
                    1.0,

                "quality_reward":
                    1.0,

                "quality_signals":
                    [],

                "workspace_before":
                    {},

                "workspace_after":
                    {},
            },
        )

    finally:
        db.close()


def test_prepare_verify_and_rollback_without_runtime_cutover(
    tmp_path: Path,
    monkeypatch,
) -> None:
    dsn = os.environ[
        "SOPHYANE_POSTGRES_DSN"
    ]

    schema = (
        "sli_cutover_test_"
        + uuid.uuid4().hex[:16]
    )

    sqlite_path = (
        tmp_path
        / "source.db"
    )

    manifest = (
        tmp_path
        / "cutover.json"
    )

    _source(
        sqlite_path
    )

    monkeypatch.setattr(
        cutover,
        "PRODUCTION_SCHEMA",
        schema,
    )

    monkeypatch.setattr(
        cutover,
        "CUTOVER_STATE",
        manifest,
    )

    store = PostgresSLIStore(
        dsn,
        schema=schema,
    )

    try:
        prepared = cutover.prepare(
            sqlite_path=sqlite_path,
            store=store,
        )

        assert prepared[
            "state"
        ] == "prepared"

        assert prepared[
            "runtime_backend"
        ] == "sqlite"

        assert store.schema_exists()

        verified = cutover.verify(
            sqlite_path=sqlite_path,
            store=store,
        )

        assert verified[
            "equivalent"
        ] is True

        assert verified[
            "runtime_backend"
        ] == "sqlite"

        rolled_back = cutover.rollback(
            sqlite_path=sqlite_path,
            store=store,
        )

        assert rolled_back[
            "state"
        ] == "rolled_back"

        assert rolled_back[
            "runtime_backend"
        ] == "sqlite"

        assert not store.schema_exists()

    finally:
        _drop_schema(
            dsn,
            schema,
        )


def test_prepare_refuses_existing_schema(
    tmp_path: Path,
    monkeypatch,
) -> None:
    dsn = os.environ[
        "SOPHYANE_POSTGRES_DSN"
    ]

    schema = (
        "sli_cutover_test_"
        + uuid.uuid4().hex[:16]
    )

    sqlite_path = (
        tmp_path
        / "source.db"
    )

    _source(
        sqlite_path
    )

    monkeypatch.setattr(
        cutover,
        "PRODUCTION_SCHEMA",
        schema,
    )

    store = PostgresSLIStore(
        dsn,
        schema=schema,
    )

    try:
        store.ensure_schema()

        try:
            cutover.prepare(
                sqlite_path=sqlite_path,
                store=store,
            )

        except RuntimeError as error:
            assert (
                "already exists"
                in str(
                    error
                )
            )

        else:
            raise AssertionError(
                "existing schema was not refused"
            )

    finally:
        _drop_schema(
            dsn,
            schema,
        )
