from pathlib import Path

from sophyane.local_coding_capability import (
    _RepairTransaction,
)


def test_transaction_detects_protected_change(
    tmp_path: Path,
) -> None:
    production = (
        tmp_path
        / "production.py"
    )

    test_file = (
        tmp_path
        / "test_production.py"
    )

    production.write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )

    test_file.write_text(
        "assert True\n",
        encoding="utf-8",
    )

    tx = _RepairTransaction.begin(
        workspace=tmp_path,
        writable={
            production,
        },
        protected={
            test_file,
        },
    )

    production.write_text(
        "VALUE = 2\n",
        encoding="utf-8",
    )

    assert (
        tx.protected_changes()
        == []
    )

    test_file.write_text(
        "assert False\n",
        encoding="utf-8",
    )

    assert tx.protected_changes() == [
        "test_production.py",
    ]


def test_transaction_rollback_restores_files(
    tmp_path: Path,
) -> None:
    production = (
        tmp_path
        / "production.py"
    )

    protected = (
        tmp_path
        / "protected.py"
    )

    production.write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )

    protected.write_text(
        "SAFE = True\n",
        encoding="utf-8",
    )

    tx = _RepairTransaction.begin(
        workspace=tmp_path,
        writable={
            production,
        },
        protected={
            protected,
        },
    )

    production.write_text(
        "VALUE = 999\n",
        encoding="utf-8",
    )

    protected.write_text(
        "SAFE = False\n",
        encoding="utf-8",
    )

    tx.rollback()

    assert production.read_text(
        encoding="utf-8",
    ) == "VALUE = 1\n"

    assert protected.read_text(
        encoding="utf-8",
    ) == "SAFE = True\n"
