from __future__ import annotations

import os
from pathlib import Path


def test_pytest_uses_isolated_sqlite_path(
    tmp_path,
    tmp_path_factory,
):
    from sophyane import sli

    path = Path(
        sli.DB_PATH
    ).expanduser().resolve()

    production = Path(
        "~/.local/state/sophyane/sli.db"
    ).expanduser().resolve()

    workspace = tmp_path.resolve()

    pytest_root = (
        tmp_path_factory
        .getbasetemp()
        .resolve()
    )

    assert path != production

    assert str(path).startswith(
        str(pytest_root)
    )

    # Critical filesystem-isolation contract:
    # the SLI DB must NOT be created in the test workspace.
    assert not str(path).startswith(
        str(workspace) + os.sep
    )

    assert path.name == "sli.db"


def test_pytest_sqlite_isolation_does_not_pollute_workspace(
    tmp_path,
):
    from sophyane import sli

    (tmp_path / "alpha").mkdir()

    assert sorted(
        item.name
        for item in tmp_path.iterdir()
    ) == ["alpha"]

    assert (
        Path(sli.DB_PATH).resolve().parent
        != tmp_path.resolve()
    )


def test_pytest_does_not_inherit_production_postgres():
    assert (
        os.environ.get(
            "SOPHYANE_POSTGRES_DSN"
        )
        is None
    )


def test_pytest_defaults_to_non_atomic_sqlite():
    assert (
        os.environ.get(
            "SOPHYANE_SLI_BACKEND"
        )
        == "sqlite"
    )

    assert (
        os.environ.get(
            "SOPHYANE_SLI_ATOMIC_LEARNING"
        )
        == "false"
    )
