"""Global pytest isolation from Sophyane production SLI.

Production configuration may intentionally select PostgreSQL and atomic
learning. Tests must never inherit that selection implicitly.

Individual PostgreSQL tests remain free to opt in explicitly with
monkeypatch.setenv() after this autouse fixture has established the
safe baseline.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_sophyane_production_sli(
    monkeypatch,
    tmp_path_factory,
):
    # SOPHYANE_PYTEST_PRODUCTION_SLI_ISOLATION_V3
    #
    # Ordinary pytest execution must never inherit either
    # production PostgreSQL or the production SQLite path.
    #
    # Keep the isolated SLI database outside each test's
    # tmp_path/workspace so filesystem tests observe only
    # artifacts created by the test itself.
    from sophyane import sli

    isolated_root = tmp_path_factory.mktemp(
        "sophyane-sli"
    )

    isolated_db = (
        isolated_root
        / "sli.db"
    )

    monkeypatch.setenv(
        "SOPHYANE_SLI_BACKEND",
        "sqlite",
    )
    monkeypatch.setenv(
        "SOPHYANE_SLI_ATOMIC_LEARNING",
        "false",
    )
    monkeypatch.delenv(
        "SOPHYANE_POSTGRES_DSN",
        raising=False,
    )

    monkeypatch.setattr(
        sli,
        "DB_PATH",
        isolated_db,
    )


@pytest.fixture
def postgres_test_dsn(monkeypatch):
    """Explicit opt-in PostgreSQL DSN for isolated PostgreSQL tests.

    The production SOPHYANE_POSTGRES_DSN remains unavailable to
    ordinary pytest tests. PostgreSQL integration tests must receive
    their connection explicitly through SOPHYANE_TEST_POSTGRES_DSN.
    """
    # SOPHYANE_PYTEST_POSTGRES_TEST_DSN_V1
    import os

    dsn = str(
        os.environ.get(
            "SOPHYANE_TEST_POSTGRES_DSN",
            "",
        )
    ).strip()

    if not dsn:
        pytest.skip(
            "SOPHYANE_TEST_POSTGRES_DSN is not configured"
        )

    monkeypatch.setenv(
        "SOPHYANE_POSTGRES_DSN",
        dsn,
    )

    return dsn
