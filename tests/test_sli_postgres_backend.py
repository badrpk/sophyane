from __future__ import annotations

import math
import os
import uuid

import psycopg
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


def test_postgres_sli_record_recommend_stats_and_trace() -> None:
    dsn = os.environ[
        "SOPHYANE_POSTGRES_DSN"
    ]

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
