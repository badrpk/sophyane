from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from sophyane import sli
from sophyane import sli_backend
from sophyane.sli_postgres import (
    PostgresSLIStore,
)


def test_default_selector_is_sqlite(
    monkeypatch,
) -> None:
    monkeypatch.delenv(
        "SOPHYANE_SLI_BACKEND",
        raising=False,
    )

    assert (
        sli_backend.selected_backend()
        == "sqlite"
    )

    with sli_backend.connect() as db:
        assert isinstance(
            db,
            sqlite3.Connection,
        )


def test_empty_selector_is_sqlite(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "SOPHYANE_SLI_BACKEND",
        "",
    )

    assert (
        sli_backend.selected_backend()
        == "sqlite"
    )


def test_invalid_selector_is_rejected(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "SOPHYANE_SLI_BACKEND",
        "invalid-backend",
    )

    with pytest.raises(
        RuntimeError,
        match="Unsupported SLI backend",
    ):
        sli_backend.selected_backend()


def test_explicit_path_remains_sqlite_under_postgres_selection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "SOPHYANE_SLI_BACKEND",
        "postgres",
    )

    target = (
        tmp_path
        / "explicit.db"
    )

    with sli_backend.connect(
        target
    ) as db:
        assert isinstance(
            db,
            sqlite3.Connection,
        )

        memory_id = (
            sli_backend.record(
                db,
                request="compatibility",
                action="TEST",
                reward=1.0,
            )
        )

        assert memory_id == 1


def test_explicit_postgres_selection_reads_prepared_schema(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "SOPHYANE_SLI_BACKEND",
        "postgres",
    )

    with sli_backend.connect() as db:
        assert isinstance(
            db,
            PostgresSLIStore,
        )

        stats = sli_backend.stats(
            db
        )

        assert stats[
            "learned_executions"
        ] == 117


def test_postgres_public_read_parity(
    monkeypatch,
) -> None:
    monkeypatch.delenv(
        "SOPHYANE_SLI_BACKEND",
        raising=False,
    )

    with sli_backend.connect() as sqlite_db:
        sqlite_stats = sli_backend.stats(
            sqlite_db
        )

        sqlite_traces = (
            sli_backend.list_traces(
                sqlite_db,
                limit=10,
            )
        )

    monkeypatch.setenv(
        "SOPHYANE_SLI_BACKEND",
        "postgres",
    )

    with sli_backend.connect() as postgres_db:
        postgres_stats = (
            sli_backend.stats(
                postgres_db
            )
        )

        postgres_traces = (
            sli_backend.list_traces(
                postgres_db,
                limit=10,
            )
        )

    for key in (
        "learned_executions",
        "distinct_actions",
        "positive_outcomes",
        "negative_outcomes",
        "sources",
    ):
        assert (
            sqlite_stats[
                key
            ]
            ==
            postgres_stats[
                key
            ]
        )

    def normalize(
        rows,
    ):
        result = []

        for row in rows:
            value = dict(
                row
            )

            for key in (
                "quality_signals",
                "workspace_before",
                "workspace_after",
            ):
                current = value.get(
                    key
                )

                if isinstance(
                    current,
                    str,
                ):
                    value[
                        key
                    ] = json.loads(
                        current
                    )

            result.append(
                value
            )

        return result

    assert normalize(
        sqlite_traces
    ) == normalize(
        postgres_traces
    )


def test_selector_does_not_modify_legacy_sli_connect(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "SOPHYANE_SLI_BACKEND",
        "postgres",
    )

    db = sli.connect()

    try:
        assert isinstance(
            db,
            sqlite3.Connection,
        )

    finally:
        db.close()
