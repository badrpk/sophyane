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


def test_synchronize_postgres_to_sqlite_appends_exact_delta(
    tmp_path,
    monkeypatch,
):
    import sqlite3

    from sophyane import sli
    import sophyane.sli_backend as sli_backend
    import sophyane.sli_cutover as cutover
    import sophyane.sli_learner as learner
    from sophyane.sli_migrate_postgres import (
        migrate,
        sqlite_snapshot,
        verify_snapshots,
    )
    from sophyane.sli_postgres import (
        PostgresSLIStore,
    )

    sqlite_path = (
        tmp_path
        / "rollback.db"
    )

    source = sqlite3.connect(
        f"file:{sli.DB_PATH.resolve()}?mode=ro",
        uri=True,
    )

    target = sqlite3.connect(
        sqlite_path
    )

    try:
        source.backup(
            target
        )

    finally:
        target.close()
        source.close()

    schema = (
        "sli_cutover_test_sync_"
        + __import__("uuid").uuid4().hex[:12]
    )

    store = PostgresSLIStore(
        schema=schema,
    )

    try:
        migrate(
            sqlite_path=sqlite_path,
            store=store,
        )

        baseline = sqlite_snapshot(
            sqlite_path
        )

        baseline_memories = len(
            baseline["memories"]
        )

        baseline_traces = len(
            baseline["traces"]
        )

        expected_memory_id = (
            max(
                int(row["id"])
                for row in baseline["memories"]
            )
            + 1
        )

        monkeypatch.setenv(
            "SOPHYANE_SLI_BACKEND",
            "postgres",
        )

        monkeypatch.setattr(
            sli_backend,
            "postgres_store",
            lambda:
                store,
        )

        # This test validates explicit/manual cutover synchronization.
        # Automatic production rollback mirroring is covered separately
        # and must never target the live SQLite database from this
        # disposable PostgreSQL test schema.
        monkeypatch.setattr(
            sli_backend,
            "synchronize_rollback_mirror",
            lambda: None,
        )

        result = learner.learn_execution(
            trace_id=(
                "phase2q-sync-"
                + __import__("uuid").uuid4().hex[:12]
            ),
            request=(
                "PHASE 2Q synchronization test"
            ),
            workspace_before={
                "phase":
                    "2Q",
            },
            workspace_after={
                "phase":
                    "2Q",

                "written":
                    True,
            },
            status="succeeded",
            reward=1.0,
            result="PHASE 2Q OK",
            elapsed_seconds=0.001,
        )

        assert result[
            "memory_id"
        ] == expected_memory_id

        before = sqlite_snapshot(
            sqlite_path
        )

        postgres = store.export_snapshot()

        assert len(
            before["memories"]
        ) == baseline_memories

        assert len(
            before["traces"]
        ) == baseline_traces

        assert len(
            postgres["memories"]
        ) == baseline_memories + 1

        assert len(
            postgres["traces"]
        ) == baseline_traces + 1

        synchronization = (
            cutover.synchronize_postgres_to_sqlite(
                sqlite_path=sqlite_path,
                store=store,
            )
        )

        assert synchronization[
            "state"
        ] == "synchronized"

        assert synchronization[
            "memories_added"
        ] == 1

        assert synchronization[
            "traces_added"
        ] == 1

        after = sqlite_snapshot(
            sqlite_path
        )

        verification = verify_snapshots(
            after,
            postgres,
        )

        assert verification[
            "equivalent"
        ] is True

        assert verification[
            "source_memories"
        ] == baseline_memories + 1

        assert verification[
            "source_traces"
        ] == baseline_traces + 1

    finally:
        if store.schema_exists():
            store.drop_schema()


def test_synchronize_postgres_to_sqlite_is_idempotent(
    tmp_path,
):
    import sqlite3

    from sophyane import sli
    import sophyane.sli_cutover as cutover
    from sophyane.sli_migrate_postgres import (
        migrate,
    )
    from sophyane.sli_postgres import (
        PostgresSLIStore,
    )

    sqlite_path = (
        tmp_path
        / "idempotent.db"
    )

    source = sqlite3.connect(
        f"file:{sli.DB_PATH.resolve()}?mode=ro",
        uri=True,
    )

    target = sqlite3.connect(
        sqlite_path
    )

    try:
        source.backup(
            target
        )

    finally:
        target.close()
        source.close()

    schema = (
        "sli_cutover_test_idempotent_"
        + __import__("uuid").uuid4().hex[:12]
    )

    store = PostgresSLIStore(
        schema=schema,
    )

    try:
        migrate(
            sqlite_path=sqlite_path,
            store=store,
        )

        baseline = store.export_snapshot()

        baseline_memories = len(
            baseline["memories"]
        )

        baseline_traces = len(
            baseline["traces"]
        )

        result = (
            cutover.synchronize_postgres_to_sqlite(
                sqlite_path=sqlite_path,
                store=store,
            )
        )

        assert result[
            "state"
        ] == "already_converged"

        assert result[
            "memories_added"
        ] == 0

        assert result[
            "traces_added"
        ] == 0

        assert result[
            "memories"
        ] == baseline_memories

        assert result[
            "traces"
        ] == baseline_traces

    finally:
        if store.schema_exists():
            store.drop_schema()


def test_synchronize_postgres_to_sqlite_refuses_conflict(
    tmp_path,
):
    import sqlite3

    from sophyane import sli
    import sophyane.sli_cutover as cutover
    from sophyane.sli_migrate_postgres import (
        migrate,
        sqlite_snapshot,
    )
    from sophyane.sli_postgres import (
        PostgresSLIStore,
    )

    sqlite_path = (
        tmp_path
        / "conflict.db"
    )

    source = sqlite3.connect(
        f"file:{sli.DB_PATH.resolve()}?mode=ro",
        uri=True,
    )

    target = sqlite3.connect(
        sqlite_path
    )

    try:
        source.backup(
            target
        )

    finally:
        target.close()
        source.close()

    schema = (
        "sli_cutover_test_conflict_"
        + __import__("uuid").uuid4().hex[:12]
    )

    store = PostgresSLIStore(
        schema=schema,
    )

    try:
        migrate(
            sqlite_path=sqlite_path,
            store=store,
        )

        with store.connect() as connection:
            with connection.cursor() as cursor:
                from psycopg import sql

                cursor.execute(
                    sql.SQL(
                        """
                        UPDATE {}.memories
                        SET request = %s
                        WHERE id = 1
                        """
                    ).format(
                        sql.Identifier(
                            schema
                        )
                    ),
                    (
                        "conflicting row",
                    ),
                )

            connection.commit()

        before = sqlite_snapshot(
            sqlite_path
        )

        import pytest

        with pytest.raises(
            RuntimeError,
            match="conflicts with existing SQLite memory IDs",
        ):
            cutover.synchronize_postgres_to_sqlite(
                sqlite_path=sqlite_path,
                store=store,
            )

        after = sqlite_snapshot(
            sqlite_path
        )

        assert before == after

    finally:
        if store.schema_exists():
            store.drop_schema()


def test_synchronize_postgres_to_sqlite_refuses_noncontiguous_memory_ids(
    tmp_path,
):
    import sqlite3

    from sophyane import sli
    import sophyane.sli_cutover as cutover
    from sophyane.sli_migrate_postgres import (
        migrate,
        sqlite_snapshot,
    )
    from sophyane.sli_postgres import (
        PostgresSLIStore,
    )

    sqlite_path = (
        tmp_path
        / "gap.db"
    )

    source = sqlite3.connect(
        f"file:{sli.DB_PATH.resolve()}?mode=ro",
        uri=True,
    )

    target = sqlite3.connect(
        sqlite_path
    )

    try:
        source.backup(
            target
        )

    finally:
        target.close()
        source.close()

    schema = (
        "sli_cutover_test_gap_"
        + __import__("uuid").uuid4().hex[:12]
    )

    store = PostgresSLIStore(
        schema=schema,
    )

    try:
        migrate(
            sqlite_path=sqlite_path,
            store=store,
        )

        payload = dict(
            store.export_snapshot()[
                "memories"
            ][-1]
        )

        payload[
            "id"
        ] = (
            int(
                payload["id"]
            )
            + 2
        )

        payload[
            "request"
        ] = "non-contiguous rollback row"

        store.import_memory(
            payload
        )

        before = sqlite_snapshot(
            sqlite_path
        )

        import pytest

        with pytest.raises(
            RuntimeError,
            match="not one contiguous append-only sequence",
        ):
            cutover.synchronize_postgres_to_sqlite(
                sqlite_path=sqlite_path,
                store=store,
            )

        after = sqlite_snapshot(
            sqlite_path
        )

        assert before == after

    finally:
        if store.schema_exists():
            store.drop_schema()


def test_rollback_synchronized_preserves_postgres_only_learning(
    tmp_path,
    monkeypatch,
):
    import sqlite3

    from sophyane import sli
    import sophyane.sli_backend as sli_backend
    import sophyane.sli_cutover as cutover
    import sophyane.sli_learner as learner
    from sophyane.sli_migrate_postgres import (
        migrate,
        sqlite_snapshot,
    )
    from sophyane.sli_postgres import (
        PostgresSLIStore,
    )

    sqlite_path = (
        tmp_path
        / "full-rollback.db"
    )

    source = sqlite3.connect(
        f"file:{sli.DB_PATH.resolve()}?mode=ro",
        uri=True,
    )

    target = sqlite3.connect(
        sqlite_path
    )

    try:
        source.backup(
            target
        )

    finally:
        target.close()
        source.close()

    schema = (
        "sli_cutover_test_rollback_sync_"
        + __import__("uuid").uuid4().hex[:12]
    )

    manifest = (
        tmp_path
        / "rollback-manifest.json"
    )

    store = PostgresSLIStore(
        schema=schema,
    )

    old_schema = (
        cutover.PRODUCTION_SCHEMA
    )

    old_state = (
        cutover.CUTOVER_STATE
    )

    try:
        migrate(
            sqlite_path=sqlite_path,
            store=store,
        )

        baseline = store.export_snapshot()

        baseline_memories = len(
            baseline["memories"]
        )

        baseline_traces = len(
            baseline["traces"]
        )

        monkeypatch.setenv(
            "SOPHYANE_SLI_BACKEND",
            "postgres",
        )

        monkeypatch.setattr(
            sli_backend,
            "postgres_store",
            lambda:
                store,
        )

        # This test intentionally creates PostgreSQL-only learning before
        # exercising explicit rollback synchronization. Keep the new
        # automatic production mirror out of this isolated test fixture.
        monkeypatch.setattr(
            sli_backend,
            "synchronize_rollback_mirror",
            lambda: None,
        )

        learner.learn_execution(
            trace_id=(
                "phase2q-rollback-"
                + __import__("uuid").uuid4().hex[:12]
            ),
            request=(
                "PHASE 2Q synchronized rollback"
            ),
            workspace_before={
                "phase":
                    "2Q",
            },
            workspace_after={
                "phase":
                    "2Q",

                "written":
                    True,
            },
            status="succeeded",
            reward=1.0,
            result="PHASE 2Q ROLLBACK OK",
            elapsed_seconds=0.001,
        )

        assert len(
            store.export_snapshot()[
                "memories"
            ]
        ) == baseline_memories + 1

        cutover.PRODUCTION_SCHEMA = schema
        cutover.CUTOVER_STATE = manifest

        result = cutover.rollback_synchronized(
            sqlite_path=sqlite_path,
            store=store,
        )

        print(
            "rollback result:",
            result,
        )

        assert result[
            "state"
        ] == "rolled_back_synchronized"

        assert result[
            "memories_added"
        ] == 1

        assert result[
            "traces_added"
        ] == 1

        assert result[
            "memories"
        ] == baseline_memories + 1

        assert result[
            "traces"
        ] == baseline_traces + 1

        assert not store.schema_exists()

        final = sqlite_snapshot(
            sqlite_path
        )

        assert len(
            final["memories"]
        ) == baseline_memories + 1

        assert len(
            final["traces"]
        ) == baseline_traces + 1

        assert manifest.is_file()

    finally:
        cutover.PRODUCTION_SCHEMA = (
            old_schema
        )

        cutover.CUTOVER_STATE = (
            old_state
        )

        if store.schema_exists():
            store.drop_schema()
