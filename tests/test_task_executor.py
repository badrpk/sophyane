from __future__ import annotations

from pathlib import Path

from sophyane.task_compiler import (
    CompiledTask,
    Evidence,
    Grounding,
    Requirement,
)
from sophyane.task_executor import (
    execute_compiled_task,
    executor_catalog,
)


def make_workspace(
    root: Path,
) -> None:
    (
        root
        / "shop"
    ).mkdir(
        parents=True
    )

    (
        root
        / "migrations"
    ).mkdir(
        parents=True
    )

    (
        root
        / "shop"
        / "models.py"
    ).write_text(
        "class Order:\n"
        "    __tablename__ = 'orders'\n"
        "    user_id = 1\n"
        "    status = 'new'\n"
        "    created_at = None\n",
        encoding="utf-8",
    )

    (
        root
        / "migrations"
        / "001_create_orders.sql"
    ).write_text(
        "CREATE TABLE orders (\n"
        " user_id INTEGER,\n"
        " status TEXT,\n"
        " created_at TIMESTAMP\n"
        ");\n",
        encoding="utf-8",
    )

    (
        root
        / "shop"
        / "repository.py"
    ).write_text(
        '''from typing import Any


def list_orders_for_user(
    session: Any,
    user_id: int,
    status: str,
):
    return (
        session.query("orders")
        .filter_by(
            user_id=user_id,
            status=status,
        )
        .order_by("created_at DESC")
        .all()
    )


def load_orders_with_items(
    session: Any,
):
    orders = session.query("orders").all()

    result = []

    for order in orders:
        items = (
            session.query("order_items")
            .filter_by(
                order_id=order.id,
            )
            .all()
        )

        result.append(
            (
                order,
                items,
            )
        )

    return result
''',
        encoding="utf-8",
    )


def compiled() -> CompiledTask:
    requirements = [
        Requirement(
            requirement_id="r1",
            text=(
                "Analyze slow queries on the orders table"
            ),
            difficulty=2,
            explicit_facts=(
                "table:orders",
            ),
        ),
        Requirement(
            requirement_id="r2",
            text=(
                "Add composite index on the orders table "
                "(user_id, status, created_at)"
            ),
            difficulty=3,
            explicit_facts=(
                "table:orders",
            ),
        ),
        Requirement(
            requirement_id="r3",
            text=(
                "rewrite N+1 ORM queries "
                "using eager loading"
            ),
            difficulty=2,
            explicit_facts=(
                "table:orders",
            ),
        ),
    ]

    return CompiledTask(
        handled=True,
        ok=True,
        difficulty=5,
        requirements=requirements,
        evidence={
            "r1": Evidence(
                value=(
                    "EXPLAIN SELECT * FROM orders "
                    "WHERE user_id = ?;"
                ),
                provenance="TEST",
                valid=True,
            ),
            "r2": Evidence(
                value=(
                    "CREATE INDEX idx_orders "
                    "ON orders "
                    "(user_id, status, created_at);"
                ),
                provenance="TEST",
                valid=True,
            ),
            "r3": Evidence(
                value=(
                    "session.query(Order).options("
                    "joinedload(Order.items)).all()"
                ),
                provenance="TEST",
                valid=True,
            ),
        },
        groundings={
            "r1": [
                Grounding(
                    requirement_id="r1",
                    path="shop/repository.py",
                    kind="query_layer",
                ),
            ],
            "r2": [
                Grounding(
                    requirement_id="r2",
                    path="migrations/001_create_orders.sql",
                    kind="migration_or_sql",
                ),
            ],
            "r3": [
                Grounding(
                    requirement_id="r3",
                    path="shop/repository.py",
                    kind="query_layer",
                ),
            ],
        },
        execution_plan=[
            {
                "requirement_id": "r1",
                "contract": "database_analysis",
                "operation": "inspect_query_path",
                "validated_value": (
                    "EXPLAIN SELECT * FROM orders "
                    "WHERE user_id = ?;"
                ),
                "targets": [
                    {
                        "path": "shop/repository.py",
                        "kind": "query_layer",
                    },
                ],
                "dry_run": True,
            },
            {
                "requirement_id": "r2",
                "contract": "database_index",
                "operation": "modify_schema_or_migration",
                "validated_value": (
                    "CREATE INDEX idx_orders "
                    "ON orders "
                    "(user_id, status, created_at);"
                ),
                "targets": [
                    {
                        "path": (
                            "migrations/"
                            "001_create_orders.sql"
                        ),
                        "kind": "migration_or_sql",
                    },
                ],
                "dry_run": True,
            },
            {
                "requirement_id": "r3",
                "contract": "orm_eager_fetch",
                "operation": "modify_query_layer",
                "validated_value": (
                    "session.query(Order).options("
                    "joinedload(Order.items)).all()"
                ),
                "targets": [
                    {
                        "path": "shop/repository.py",
                        "kind": "query_layer",
                    },
                ],
                "dry_run": True,
            },
        ],
    )


def test_executor_registry_has_proven_contracts():
    assert set(
        executor_catalog()
    ) >= {
        "database_analysis",
        "database_index",
        "orm_eager_fetch",
    }


def test_full_executor_pipeline(
    tmp_path: Path,
):
    make_workspace(
        tmp_path
    )

    result = execute_compiled_task(
        compiled(),
        workspace=tmp_path,
    )

    assert result.ok
    assert len(result.steps) == 3
    assert all(
        item.ok
        for item in result.steps
    )

    assert (
        tmp_path
        / "migrations"
        / "002_add_orders_pagination_index.sql"
    ).is_file()

    repository = (
        tmp_path
        / "shop"
        / "repository.py"
    ).read_text()

    function = repository.split(
        "def load_orders_with_items",
        1,
    )[1]

    assert (
        'query("order_items")'
        not in function
    )

    assert (
        "joinedload"
        in function
    )

    assert (
        tmp_path
        / ".sophyane"
        / "execution"
        / "r1-query-plan.sql"
    ).is_file()
