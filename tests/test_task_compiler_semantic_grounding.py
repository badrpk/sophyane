from __future__ import annotations

from pathlib import Path

from sophyane.task_compiler import (
    Requirement,
    ground_requirement,
)


def requirement() -> Requirement:
    return Requirement(
        requirement_id="r1",
        text=(
            "Add composite index on the orders table "
            "(user_id, status, created_at)"
        ),
        difficulty=3,
    )


def test_keyword_only_file_is_not_grounded(
    tmp_path: Path,
):
    path = tmp_path / "notes.py"

    path.write_text(
        "# benchmark text mentioning orders user_id "
        "status created_at migration schema\n",
        encoding="utf-8",
    )

    assert ground_requirement(
        requirement(),
        workspace=tmp_path,
    ) == []


def test_real_model_structure_is_grounded(
    tmp_path: Path,
):
    path = (
        tmp_path
        / "models"
        / "order.py"
    )

    path.parent.mkdir()

    path.write_text(
        "class Order:\n"
        "    __tablename__ = 'orders'\n"
        "    user_id = Column(Integer)\n"
        "    status = Column(String)\n"
        "    created_at = Column(DateTime)\n",
        encoding="utf-8",
    )

    results = ground_requirement(
        requirement(),
        workspace=tmp_path,
    )

    assert results
    assert (
        results[0].path
        == "models/order.py"
    )


def test_real_sql_schema_is_grounded(
    tmp_path: Path,
):
    path = (
        tmp_path
        / "migrations"
        / "001_orders.sql"
    )

    path.parent.mkdir()

    path.write_text(
        "CREATE TABLE orders (\n"
        "  id INTEGER PRIMARY KEY,\n"
        "  user_id INTEGER,\n"
        "  status TEXT,\n"
        "  created_at TIMESTAMP\n"
        ");\n",
        encoding="utf-8",
    )

    results = ground_requirement(
        requirement(),
        workspace=tmp_path,
    )

    assert results
    assert (
        results[0].kind
        == "migration_or_sql"
    )


def test_tests_directory_is_never_execution_target(
    tmp_path: Path,
):
    path = (
        tmp_path
        / "tests"
        / "test_orders.py"
    )

    path.parent.mkdir()

    path.write_text(
        "class Order:\n"
        "    __tablename__ = 'orders'\n"
        "    user_id = 1\n"
        "    status = 1\n"
        "    created_at = 1\n",
        encoding="utf-8",
    )

    assert ground_requirement(
        requirement(),
        workspace=tmp_path,
    ) == []
