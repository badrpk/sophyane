from __future__ import annotations

import math
import os
import uuid

import psycopg
import pytest
from psycopg import sql

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


def test_postgres_sli_record_recommend_stats_and_trace(
    postgres_test_dsn,
) -> None:
    dsn = postgres_test_dsn

    schema = (
        "sli_backend_test_"
        + uuid.uuid4().hex[:16]
    )

    store = PostgresSLIStore(
        dsn,
        schema=schema,
    )

    try:
        store.ensure_schema()

        for _ in range(
            20
        ):
            store.record(
                request="make a calculator",
                action="INSPECT_EVIDENCE",
                reward=1.0,
                source_type="scanned_log",
            )

        for _ in range(
            2
        ):
            store.record(
                request="make a calculator",
                action="GENERATE_BROWSER_ARTIFACT",
                reward=1.0,
                source_type="execution",
            )

        recommendations = (
            store.recommend_actions(
                request=(
                    "make a simple calculator"
                ),
            )
        )

        assert recommendations[
            0
        ][
            "action"
        ] == "GENERATE_BROWSER_ARTIFACT"

        trace = {
            "trace_id":
                "trace-postgres-proof",

            "request":
                "make a calculator",

            "action":
                "GENERATE_BROWSER_ARTIFACT",

            "status":
                "succeeded",

            "reward":
                1.0,

            "quality_reward":
                1.0,

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
                                100,
                        },
                    ],
                },
        }

        store.store_trace(
            trace
        )

        traces = store.list_traces(
            limit=5,
        )

        assert len(
            traces
        ) == 1

        row = traces[
            0
        ]

        assert row[
            "trace_id"
        ] == "trace-postgres-proof"

        assert row[
            "quality_signals"
        ] == [
            "validation_passed:+0.20",
        ]

        assert row[
            "workspace_after"
        ] == {
            "sample": [
                {
                    "path":
                        "index.html",

                    "bytes":
                        100,
                },
            ],
        }

        stats = store.stats()

        assert stats[
            "learned_executions"
        ] == 22

        assert stats[
            "distinct_actions"
        ] == 2

        assert stats[
            "positive_outcomes"
        ] == 22

        assert stats[
            "negative_outcomes"
        ] == 0

        assert stats[
            "sources"
        ] == {
            "execution":
                2,

            "scanned_log":
                20,
        }

        assert math.isclose(
            stats[
                "average_reward"
            ],
            1.0,
        )

    finally:
        _drop_schema(
            dsn,
            schema,
        )


def test_postgres_atomic_learner_event_idempotency(
    postgres_test_dsn,
) -> None:
    dsn = postgres_test_dsn

    schema = (
        "sli_atomic_event_test_"
        + uuid.uuid4().hex[:16]
    )

    store = PostgresSLIStore(
        dsn,
        schema=schema,
    )

    trace_id = (
        "atomic-event-"
        + uuid.uuid4().hex[:16]
    )

    try:
        store.ensure_schema()
        store.ensure_learner_event_keys_schema()

        memory = {
            "request":
                "atomic learner event",

            "state":
                "execution completed",

            "action":
                "EXECUTE_STRUCTURED_TASK",

            "result":
                "created",

            "reward":
                0.45,

            "confidence":
                1.0,

            "elapsed_seconds":
                0.001,

            "source_type":
                "execution",
        }

        trace = {
            "trace_id":
                trace_id,

            "request":
                "atomic learner event",

            "action":
                "EXECUTE_STRUCTURED_TASK",

            "status":
                "succeeded",

            "reward":
                0.45,

            "quality_reward":
                0.45,

            "failure_category":
                "",

            "quality_signals":
                [
                    "successful_status:+0.35",
                    "no_detected_runtime_error:+0.10",
                ],

            "result":
                "created",

            "elapsed_seconds":
                0.001,

            "workspace_before":
                {
                    "attempt": 1,
                },

            "workspace_after":
                {
                    "attempt": 1,
                    "completed": True,
                },
        }

        digest = (
            "a"
            * 64
        )

        first = store.atomic_learn_execution(
            trace_id=trace_id,
            payload_digest=digest,
            memory=memory,
            trace=trace,
        )

        assert first == {
            "state":
                "created",

            "trace_id":
                trace_id,

            "memory_id":
                1,

            "payload_digest":
                digest,

            "created":
                True,
        }

        retry = store.atomic_learn_execution(
            trace_id=trace_id,
            payload_digest=digest,
            memory={
                **memory,
                "result":
                    "MUST NOT REWRITE MEMORY",
            },
            trace={
                **trace,
                "result":
                    "MUST NOT REWRITE TRACE",
            },
        )

        assert retry == {
            "state":
                "already_recorded",

            "trace_id":
                trace_id,

            "memory_id":
                1,

            "payload_digest":
                digest,

            "created":
                False,
        }

        key = store.get_learner_event_key(
            trace_id
        )

        assert key is not None
        assert key[
            "memory_id"
        ] == 1
        assert key[
            "payload_digest"
        ] == digest

        snapshot = store.export_snapshot()

        assert len(
            snapshot[
                "memories"
            ]
        ) == 1

        assert len(
            snapshot[
                "traces"
            ]
        ) == 1

        assert snapshot[
            "memories"
        ][0][
            "result"
        ] == "created"

        assert snapshot[
            "traces"
        ][0][
            "result"
        ] == "created"

        with pytest.raises(
            RuntimeError,
            match="payload conflict",
        ):
            store.atomic_learn_execution(
                trace_id=trace_id,
                payload_digest=(
                    "b"
                    * 64
                ),
                memory=memory,
                trace=trace,
            )

        after_conflict = (
            store.export_snapshot()
        )

        assert len(
            after_conflict[
                "memories"
            ]
        ) == 1

        assert len(
            after_conflict[
                "traces"
            ]
        ) == 1

    finally:
        _drop_schema(
            dsn,
            schema,
        )


def test_postgres_atomic_learner_event_rolls_back_before_key_commit(
    postgres_test_dsn,
) -> None:
    dsn = postgres_test_dsn

    schema = (
        "sli_atomic_rollback_test_"
        + uuid.uuid4().hex[:16]
    )

    store = PostgresSLIStore(
        dsn,
        schema=schema,
    )

    trace_id = (
        "atomic-rollback-"
        + uuid.uuid4().hex[:16]
    )

    try:
        store.ensure_schema()
        store.ensure_learner_event_keys_schema()

        # Cause only the final event-key insert to fail. The preceding
        # memory and trace writes must roll back with the transaction.
        with psycopg.connect(
            dsn
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        """
                        ALTER TABLE {}.learner_event_keys
                        ADD CONSTRAINT
                        learner_event_keys_test_digest_check
                        CHECK (
                            payload_digest
                            <> 'force-rollback'
                        )
                        """
                    ).format(
                        sql.Identifier(
                            schema
                        )
                    )
                )

            connection.commit()

        with pytest.raises(
            psycopg.errors.CheckViolation
        ):
            store.atomic_learn_execution(
                trace_id=trace_id,
                payload_digest="force-rollback",
                memory={
                    "request":
                        "rollback atomic event",

                    "state":
                        "execution completed",

                    "action":
                        "EXECUTE_STRUCTURED_TASK",

                    "result":
                        "must rollback",

                    "reward":
                        0.45,

                    "confidence":
                        1.0,

                    "elapsed_seconds":
                        0.001,

                    "source_type":
                        "execution",
                },
                trace={
                    "trace_id":
                        trace_id,

                    "request":
                        "rollback atomic event",

                    "action":
                        "EXECUTE_STRUCTURED_TASK",

                    "status":
                        "succeeded",

                    "reward":
                        0.45,

                    "quality_reward":
                        0.45,

                    "failure_category":
                        "",

                    "quality_signals":
                        [],

                    "result":
                        "must rollback",

                    "elapsed_seconds":
                        0.001,

                    "workspace_before":
                        {},

                    "workspace_after":
                        {},
                },
            )

        snapshot = store.export_snapshot()

        assert snapshot[
            "memories"
        ] == []

        assert snapshot[
            "traces"
        ] == []

        assert (
            store.get_learner_event_key(
                trace_id
            )
            is None
        )

    finally:
        _drop_schema(
            dsn,
            schema,
        )


def test_postgres_atomic_same_payload_concurrent_callers(
    postgres_test_dsn,
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    import threading

    dsn = postgres_test_dsn

    schema = (
        "sli_atomic_same_race_"
        + uuid.uuid4().hex[:16]
    )

    trace_id = (
        "atomic-same-race-"
        + uuid.uuid4().hex[:16]
    )

    store = PostgresSLIStore(
        dsn,
        schema=schema,
    )

    workers = 8

    try:
        store.ensure_schema()
        store.ensure_learner_event_keys_schema()

        barrier = threading.Barrier(
            workers
        )

        memory = {
            "request":
                "concurrent same-payload learner event",

            "state":
                "execution completed",

            "action":
                "EXECUTE_STRUCTURED_TASK",

            "result":
                "same payload",

            "reward":
                0.45,

            "confidence":
                1.0,

            "elapsed_seconds":
                0.001,

            "source_type":
                "execution",
        }

        trace = {
            "trace_id":
                trace_id,

            "request":
                "concurrent same-payload learner event",

            "action":
                "EXECUTE_STRUCTURED_TASK",

            "status":
                "succeeded",

            "reward":
                0.45,

            "quality_reward":
                0.45,

            "failure_category":
                "",

            "quality_signals":
                [
                    "successful_status:+0.35",
                    "no_detected_runtime_error:+0.10",
                ],

            "result":
                "same payload",

            "elapsed_seconds":
                0.001,

            "workspace_before":
                {
                    "race":
                        "same-payload",
                },

            "workspace_after":
                {
                    "race":
                        "same-payload",

                    "completed":
                        True,
                },
        }

        payload_digest = (
            "c"
            * 64
        )

        def invoke() -> dict:
            barrier.wait(
                timeout=10
            )

            return store.atomic_learn_execution(
                trace_id=trace_id,
                payload_digest=payload_digest,
                memory=memory,
                trace=trace,
            )

        with ThreadPoolExecutor(
            max_workers=workers
        ) as executor:
            futures = [
                executor.submit(
                    invoke
                )
                for _ in range(
                    workers
                )
            ]

            results = [
                future.result(
                    timeout=30
                )
                for future in futures
            ]

        created = [
            result
            for result in results
            if result[
                "state"
            ] == "created"
        ]

        replayed = [
            result
            for result in results
            if result[
                "state"
            ] == "already_recorded"
        ]

        assert len(created) == 1

        assert len(
            replayed
        ) == (
            workers - 1
        )

        memory_ids = {
            int(
                result[
                    "memory_id"
                ]
            )
            for result in results
        }

        assert len(
            memory_ids
        ) == 1

        memory_id = next(
            iter(
                memory_ids
            )
        )

        key = store.get_learner_event_key(
            trace_id
        )

        assert key is not None

        assert key[
            "memory_id"
        ] == memory_id

        assert key[
            "payload_digest"
        ] == payload_digest

        snapshot = store.export_snapshot()

        assert len(
            snapshot[
                "memories"
            ]
        ) == 1

        assert len(
            snapshot[
                "traces"
            ]
        ) == 1

        assert snapshot[
            "traces"
        ][0][
            "trace_id"
        ] == trace_id

        assert snapshot[
            "traces"
        ][0][
            "result"
        ] == "same payload"

    finally:
        _drop_schema(
            dsn,
            schema,
        )


def test_postgres_atomic_conflicting_concurrent_callers(
    postgres_test_dsn,
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    import threading

    dsn = postgres_test_dsn

    schema = (
        "sli_atomic_conflict_race_"
        + uuid.uuid4().hex[:16]
    )

    trace_id = (
        "atomic-conflict-race-"
        + uuid.uuid4().hex[:16]
    )

    store = PostgresSLIStore(
        dsn,
        schema=schema,
    )

    try:
        store.ensure_schema()
        store.ensure_learner_event_keys_schema()

        barrier = threading.Barrier(
            2
        )

        payloads = [
            {
                "digest":
                    "d"
                    * 64,

                "result":
                    "payload A",
            },
            {
                "digest":
                    "e"
                    * 64,

                "result":
                    "payload B",
            },
        ]

        def invoke(
            item: dict,
        ) -> tuple[str, object]:
            barrier.wait(
                timeout=10
            )

            try:
                result = (
                    store.atomic_learn_execution(
                        trace_id=trace_id,

                        payload_digest=item[
                            "digest"
                        ],

                        memory={
                            "request":
                                "concurrent conflicting event",

                            "state":
                                "execution completed",

                            "action":
                                "EXECUTE_STRUCTURED_TASK",

                            "result":
                                item[
                                    "result"
                                ],

                            "reward":
                                0.45,

                            "confidence":
                                1.0,

                            "elapsed_seconds":
                                0.001,

                            "source_type":
                                "execution",
                        },

                        trace={
                            "trace_id":
                                trace_id,

                            "request":
                                "concurrent conflicting event",

                            "action":
                                "EXECUTE_STRUCTURED_TASK",

                            "status":
                                "succeeded",

                            "reward":
                                0.45,

                            "quality_reward":
                                0.45,

                            "failure_category":
                                "",

                            "quality_signals":
                                [],

                            "result":
                                item[
                                    "result"
                                ],

                            "elapsed_seconds":
                                0.001,

                            "workspace_before":
                                {
                                    "payload":
                                        item[
                                            "result"
                                        ],
                                },

                            "workspace_after":
                                {
                                    "payload":
                                        item[
                                            "result"
                                        ],

                                    "completed":
                                        True,
                                },
                        },
                    )
                )

                return (
                    "returned",
                    result,
                )

            except RuntimeError as error:
                return (
                    "conflict",
                    str(
                        error
                    ),
                )

        with ThreadPoolExecutor(
            max_workers=2
        ) as executor:
            futures = [
                executor.submit(
                    invoke,
                    item,
                )
                for item in payloads
            ]

            outcomes = [
                future.result(
                    timeout=30
                )
                for future in futures
            ]

        returned = [
            value
            for kind, value in outcomes
            if kind == "returned"
        ]

        conflicts = [
            value
            for kind, value in outcomes
            if kind == "conflict"
        ]

        assert len(
            returned
        ) == 1

        assert len(
            conflicts
        ) == 1

        assert returned[
            0
        ][
            "state"
        ] == "created"

        assert (
            "payload conflict"
            in conflicts[
                0
            ]
        )

        key = store.get_learner_event_key(
            trace_id
        )

        assert key is not None

        assert key[
            "payload_digest"
        ] in {
            "d" * 64,
            "e" * 64,
        }

        snapshot = store.export_snapshot()

        assert len(
            snapshot[
                "memories"
            ]
        ) == 1

        assert len(
            snapshot[
                "traces"
            ]
        ) == 1

        winning_result = (
            "payload A"
            if key[
                "payload_digest"
            ] == (
                "d"
                * 64
            )
            else
            "payload B"
        )

        assert snapshot[
            "memories"
        ][0][
            "result"
        ] == winning_result

        assert snapshot[
            "traces"
        ][0][
            "result"
        ] == winning_result

    finally:
        _drop_schema(
            dsn,
            schema,
        )


def test_atomic_learner_integration_mirror_failure_retry(
    monkeypatch,
    tmp_path,
    postgres_test_dsn,
) -> None:
    import sophyane.sli_backend as backend
    import sophyane.sli_cutover as cutover
    import sophyane.sli_learner as learner
    from sophyane import sli as sqlite_sli

    dsn = postgres_test_dsn

    schema = (
        "sli_atomic_integration_"
        + uuid.uuid4().hex[:16]
    )

    trace_id = (
        "atomic-integration-"
        + uuid.uuid4().hex[:16]
    )

    sqlite_path = (
        tmp_path
        / "rollback.db"
    )

    store = PostgresSLIStore(
        dsn,
        schema=schema,
    )

    try:
        store.ensure_schema()

        store.ensure_learner_event_keys_schema()

        db = sqlite_sli.connect(
            sqlite_path
        )

        db.close()

        monkeypatch.setenv(
            "SOPHYANE_SLI_BACKEND",
            "postgres",
        )

        monkeypatch.setenv(
            "SOPHYANE_SLI_ATOMIC_LEARNING",
            "1",
        )

        monkeypatch.setattr(
            backend,
            "postgres_store",
            lambda: store,
        )

        monkeypatch.setattr(
            backend.sli,
            "DB_PATH",
            sqlite_path,
        )

        mirror_attempts = {
            "count": 0,
        }

        real_sync = (
            cutover.synchronize_postgres_to_sqlite
        )

        def flaky_mirror():
            mirror_attempts[
                "count"
            ] += 1

            if (
                mirror_attempts[
                    "count"
                ]
                == 1
            ):
                raise RuntimeError(
                    "simulated atomic mirror failure"
                )

            return real_sync(
                sqlite_path=
                    sqlite_path,

                store=
                    store,
            )

        monkeypatch.setattr(
            backend,
            "synchronize_rollback_mirror",
            flaky_mirror,
        )

        with pytest.raises(
            RuntimeError,
            match="simulated atomic mirror failure",
        ):
            learner.learn_execution(
                trace_id=
                    trace_id,

                request=
                    "atomic learner integration retry",

                workspace_before=
                    {
                        "attempt":
                            1,
                    },

                workspace_after=
                    {
                        "attempt":
                            1,

                        "completed":
                            True,
                    },

                status=
                    "succeeded",

                reward=
                    1.0,

                result=
                    "completed successfully",

                elapsed_seconds=
                    0.001,
            )

        authoritative = (
            store.export_snapshot()
        )

        mirrored_before = (
            sqlite_sli.connect(
                sqlite_path
            )
        )

        try:
            sqlite_memory_count = (
                mirrored_before.execute(
                    "SELECT count(*) FROM memories"
                ).fetchone()[0]
            )

            sqlite_trace_count = (
                mirrored_before.execute(
                    """
                    SELECT count(*)
                    FROM learned_execution_traces
                    """
                ).fetchone()[0]
            )

        finally:
            mirrored_before.close()

        assert len(
            authoritative[
                "memories"
            ]
        ) == 1

        assert len(
            authoritative[
                "traces"
            ]
        ) == 1

        assert sqlite_memory_count == 0
        assert sqlite_trace_count == 0

        retry = learner.learn_execution(
            trace_id=
                trace_id,

            request=
                "atomic learner integration retry",

            workspace_before=
                {
                    "attempt":
                        1,
                },

            workspace_after=
                {
                    "attempt":
                        1,

                    "completed":
                        True,
                },

            status=
                "succeeded",

            reward=
                1.0,

            result=
                "completed successfully",

            elapsed_seconds=
                0.001,
        )

        assert retry[
            "memory_id"
        ] == 1

        assert retry[
            "atomic_learning"
        ][
            "state"
        ] == "already_recorded"

        assert retry[
            "atomic_learning"
        ][
            "created"
        ] is False

        assert retry[
            "rollback_mirror"
        ][
            "state"
        ] == "synchronized"

        assert retry[
            "rollback_mirror"
        ][
            "memories_added"
        ] == 1

        assert retry[
            "rollback_mirror"
        ][
            "traces_added"
        ] == 1

        final_pg = (
            store.export_snapshot()
        )

        assert len(
            final_pg[
                "memories"
            ]
        ) == 1

        assert len(
            final_pg[
                "traces"
            ]
        ) == 1

        final_sqlite = (
            sqlite_sli.connect(
                sqlite_path
            )
        )

        try:
            assert (
                final_sqlite.execute(
                    "SELECT count(*) FROM memories"
                ).fetchone()[0]
                == 1
            )

            assert (
                final_sqlite.execute(
                    """
                    SELECT count(*)
                    FROM learned_execution_traces
                    """
                ).fetchone()[0]
                == 1
            )

        finally:
            final_sqlite.close()

        third = learner.learn_execution(
            trace_id=
                trace_id,

            request=
                "atomic learner integration retry",

            workspace_before=
                {
                    "attempt":
                        1,
                },

            workspace_after=
                {
                    "attempt":
                        1,

                    "completed":
                        True,
                },

            status=
                "succeeded",

            reward=
                1.0,

            result=
                "completed successfully",

            elapsed_seconds=
                0.001,
        )

        assert third[
            "memory_id"
        ] == 1

        assert third[
            "atomic_learning"
        ][
            "state"
        ] == "already_recorded"

        assert third[
            "rollback_mirror"
        ][
            "state"
        ] == "already_converged"

        final_again = (
            store.export_snapshot()
        )

        assert len(
            final_again[
                "memories"
            ]
        ) == 1

        assert len(
            final_again[
                "traces"
            ]
        ) == 1

    finally:
        _drop_schema(
            dsn,
            schema,
        )


def test_atomic_learner_integration_conflicting_retry_fails_before_mirror(
    monkeypatch,
    postgres_test_dsn,
) -> None:
    import sophyane.sli_backend as backend
    import sophyane.sli_learner as learner

    dsn = postgres_test_dsn

    schema = (
        "sli_atomic_integration_conflict_"
        + uuid.uuid4().hex[:16]
    )

    trace_id = (
        "atomic-integration-conflict-"
        + uuid.uuid4().hex[:16]
    )

    store = PostgresSLIStore(
        dsn,
        schema=schema,
    )

    mirror_calls = {
        "count": 0,
    }

    try:
        store.ensure_schema()
        store.ensure_learner_event_keys_schema()

        monkeypatch.setenv(
            "SOPHYANE_SLI_BACKEND",
            "postgres",
        )

        monkeypatch.setenv(
            "SOPHYANE_SLI_ATOMIC_LEARNING",
            "1",
        )

        monkeypatch.setattr(
            backend,
            "postgres_store",
            lambda: store,
        )

        monkeypatch.setattr(
            backend,
            "synchronize_rollback_mirror",
            lambda: (
                mirror_calls.__setitem__(
                    "count",
                    mirror_calls[
                        "count"
                    ] + 1,
                )
                or {
                    "state":
                        "simulated",
                }
            ),
        )

        first = learner.learn_execution(
            trace_id=
                trace_id,

            request=
                "atomic conflicting integration",

            workspace_before=
                {},

            workspace_after=
                {},

            status=
                "succeeded",

            reward=
                1.0,

            result=
                "first result",

            elapsed_seconds=
                0.001,
        )

        assert first[
            "atomic_learning"
        ][
            "state"
        ] == "created"

        assert mirror_calls[
            "count"
        ] == 1

        with pytest.raises(
            RuntimeError,
            match="payload conflict",
        ):
            learner.learn_execution(
                trace_id=
                    trace_id,

                request=
                    "atomic conflicting integration",

                workspace_before=
                    {},

                workspace_after=
                    {},

                status=
                    "succeeded",

                reward=
                    1.0,

                result=
                    "different result",

                elapsed_seconds=
                    0.001,
            )

        assert mirror_calls[
            "count"
        ] == 1

        snapshot = (
            store.export_snapshot()
        )

        assert len(
            snapshot[
                "memories"
            ]
        ) == 1

        assert len(
            snapshot[
                "traces"
            ]
        ) == 1

        assert snapshot[
            "memories"
        ][0][
            "result"
        ] == "first result"

        assert snapshot[
            "traces"
        ][0][
            "result"
        ] == "first result"

    finally:
        _drop_schema(
            dsn,
            schema,
        )
