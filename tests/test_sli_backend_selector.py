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

    monkeypatch.setattr(
        sli_backend,
        "load_config",
        lambda: {},
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

    monkeypatch.setattr(
        sli_backend,
        "load_config",
        lambda: {},
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
    postgres_test_dsn,
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
        ] >= 1


def test_postgres_public_read_parity(
    monkeypatch,
    postgres_test_dsn,
) -> None:
    monkeypatch.delenv(
        "SOPHYANE_SLI_BACKEND",
        raising=False,
    )

    # SOPHYANE_PYTEST_BACKEND_SELECTOR_ISOLATION_V1
    #
    # The first parity phase intentionally exercises SQLite.
    # Persistent production configuration must not override it.
    monkeypatch.setattr(
        sli_backend,
        "load_config",
        lambda: {},
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


def test_selector_defaults_to_sqlite_without_env_or_config(
    monkeypatch,
):
    import sophyane.sli_backend as sli_backend

    monkeypatch.delenv(
        "SOPHYANE_SLI_BACKEND",
        raising=False,
    )

    monkeypatch.setattr(
        sli_backend,
        "load_config",
        lambda: {},
    )

    assert (
        sli_backend.selected_backend()
        == "sqlite"
    )


def test_selector_reads_persistent_sqlite_config(
    monkeypatch,
):
    import sophyane.sli_backend as sli_backend

    monkeypatch.delenv(
        "SOPHYANE_SLI_BACKEND",
        raising=False,
    )

    monkeypatch.setattr(
        sli_backend,
        "load_config",
        lambda: {
            "sli_backend":
                "sqlite",
        },
    )

    assert (
        sli_backend.selected_backend()
        == "sqlite"
    )


def test_selector_reads_persistent_postgres_config(
    monkeypatch,
):
    import sophyane.sli_backend as sli_backend

    monkeypatch.delenv(
        "SOPHYANE_SLI_BACKEND",
        raising=False,
    )

    monkeypatch.setattr(
        sli_backend,
        "load_config",
        lambda: {
            "sli_backend":
                "postgres",
        },
    )

    assert (
        sli_backend.selected_backend()
        == "postgres"
    )


def test_environment_sqlite_overrides_persistent_postgres(
    monkeypatch,
):
    import sophyane.sli_backend as sli_backend

    monkeypatch.setenv(
        "SOPHYANE_SLI_BACKEND",
        "sqlite",
    )

    monkeypatch.setattr(
        sli_backend,
        "load_config",
        lambda: {
            "sli_backend":
                "postgres",
        },
    )

    assert (
        sli_backend.selected_backend()
        == "sqlite"
    )


def test_environment_postgres_overrides_persistent_sqlite(
    monkeypatch,
):
    import sophyane.sli_backend as sli_backend

    monkeypatch.setenv(
        "SOPHYANE_SLI_BACKEND",
        "postgres",
    )

    monkeypatch.setattr(
        sli_backend,
        "load_config",
        lambda: {
            "sli_backend":
                "sqlite",
        },
    )

    assert (
        sli_backend.selected_backend()
        == "postgres"
    )


def test_empty_environment_uses_persistent_config(
    monkeypatch,
):
    import sophyane.sli_backend as sli_backend

    monkeypatch.setenv(
        "SOPHYANE_SLI_BACKEND",
        "   ",
    )

    monkeypatch.setattr(
        sli_backend,
        "load_config",
        lambda: {
            "sli_backend":
                "postgres",
        },
    )

    assert (
        sli_backend.selected_backend()
        == "postgres"
    )


def test_invalid_persistent_backend_is_rejected(
    monkeypatch,
):
    import pytest
    import sophyane.sli_backend as sli_backend

    monkeypatch.delenv(
        "SOPHYANE_SLI_BACKEND",
        raising=False,
    )

    monkeypatch.setattr(
        sli_backend,
        "load_config",
        lambda: {
            "sli_backend":
                "invalid-backend",
        },
    )

    with pytest.raises(
        RuntimeError,
        match="Unsupported SLI backend",
    ):
        sli_backend.selected_backend()


def test_invalid_environment_override_is_rejected_even_with_valid_config(
    monkeypatch,
):
    import pytest
    import sophyane.sli_backend as sli_backend

    monkeypatch.setenv(
        "SOPHYANE_SLI_BACKEND",
        "invalid-backend",
    )

    monkeypatch.setattr(
        sli_backend,
        "load_config",
        lambda: {
            "sli_backend":
                "sqlite",
        },
    )

    with pytest.raises(
        RuntimeError,
        match="Unsupported SLI backend",
    ):
        sli_backend.selected_backend()


def test_config_load_failure_fails_closed_to_sqlite(
    monkeypatch,
):
    import sophyane.sli_backend as sli_backend

    monkeypatch.delenv(
        "SOPHYANE_SLI_BACKEND",
        raising=False,
    )

    def fail():
        raise RuntimeError(
            "simulated config failure"
        )

    monkeypatch.setattr(
        sli_backend,
        "load_config",
        fail,
    )

    assert (
        sli_backend.selected_backend()
        == "sqlite"
    )


def test_explicit_sqlite_path_remains_sqlite_even_when_persistent_postgres(
    tmp_path,
    monkeypatch,
):
    import sqlite3

    from sophyane import sli
    import sophyane.sli_backend as sli_backend

    path = tmp_path / "explicit.db"

    source = sqlite3.connect(
        f"file:{sli.DB_PATH.resolve()}?mode=ro",
        uri=True,
    )

    target = sqlite3.connect(
        path
    )

    try:
        source.backup(
            target
        )

    finally:
        target.close()
        source.close()

    monkeypatch.delenv(
        "SOPHYANE_SLI_BACKEND",
        raising=False,
    )

    monkeypatch.setattr(
        sli_backend,
        "load_config",
        lambda: {
            "sli_backend":
                "postgres",
        },
    )

    assert (
        sli_backend.selected_backend()
        == "postgres"
    )

    with sli_backend.connect(
        path
    ) as db:
        assert isinstance(
            db,
            sqlite3.Connection,
        )


def test_empty_environment_falls_through_to_persistent_postgres(
    monkeypatch,
):
    import sophyane.sli_backend as sli_backend

    monkeypatch.setenv(
        "SOPHYANE_SLI_BACKEND",
        "",
    )

    monkeypatch.setattr(
        sli_backend,
        "load_config",
        lambda: {
            "sli_backend":
                "postgres",
        },
    )

    assert (
        sli_backend.selected_backend()
        == "postgres"
    )
