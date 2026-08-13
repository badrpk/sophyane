from __future__ import annotations

import os

import sophyane.sli_backend as backend


def test_pytest_defaults_to_nonproduction_sli():
    assert (
        os.environ.get("SOPHYANE_SLI_BACKEND")
        == "sqlite"
    )

    assert (
        os.environ.get("SOPHYANE_SLI_ATOMIC_LEARNING")
        == "false"
    )

    assert "SOPHYANE_POSTGRES_DSN" not in os.environ

    assert backend.selected_backend() == "sqlite"
    assert backend.atomic_learning_enabled() is False


def test_explicit_test_postgres_opt_in_still_works(
    monkeypatch,
):
    monkeypatch.setenv(
        "SOPHYANE_POSTGRES_DSN",
        "postgresql://test:test@127.0.0.1:5432/test",
    )
    monkeypatch.setenv(
        "SOPHYANE_SLI_BACKEND",
        "postgres",
    )
    monkeypatch.setenv(
        "SOPHYANE_SLI_ATOMIC_LEARNING",
        "true",
    )

    assert backend.selected_backend() == "postgres"
    assert backend.atomic_learning_enabled() is True
