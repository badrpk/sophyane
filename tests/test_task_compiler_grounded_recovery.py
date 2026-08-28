from __future__ import annotations

from pathlib import Path

from sophyane.task_compiler import (
    Grounding,
    Requirement,
    grounded_contract_recovery,
)


def test_database_analysis_recovery_from_real_query(
    tmp_path: Path,
):
    target = (
        tmp_path
        / "shop"
        / "repository.py"
    )

    target.parent.mkdir(
        parents=True
    )

    target.write_text(
        '''
def list_orders(session, user_id, status):
    return (
        session.query("orders")
        .filter_by(
            user_id=user_id,
            status=status,
        )
        .order_by("created_at DESC")
        .all()
    )
''',
        encoding="utf-8",
    )

    requirement = Requirement(
        requirement_id="r1",
        text=(
            "Analyze slow queries on the orders table "
            "generating high DB CPU load"
        ),
        difficulty=2,
        explicit_facts=(
            "table:orders",
        ),
    )

    result = grounded_contract_recovery(
        requirement,
        grounding=Grounding(
            requirement_id="r1",
            path="shop/repository.py",
            kind="query_layer",
        ),
        workspace=tmp_path,
    )

    assert result.valid
    assert (
        result.provenance
        == "GROUNDED_DETERMINISTIC"
    )
    assert "EXPLAIN" in result.value
    assert "orders" in result.value


def test_n_plus_one_recovery_from_real_problem_site(
    tmp_path: Path,
):
    target = (
        tmp_path
        / "shop"
        / "repository.py"
    )

    target.parent.mkdir(
        parents=True
    )

    target.write_text(
        '''
def load_orders_with_items(session):
    orders = session.query("orders").all()

    result = []

    for order in orders:
        items = (
            session.query("order_items")
            .filter_by(order_id=order.id)
            .all()
        )

        result.append((order, items))

    return result
''',
        encoding="utf-8",
    )

    requirement = Requirement(
        requirement_id="r3",
        text=(
            "rewrite N+1 ORM queries using explicit "
            "JOIN FETCH / eager_load"
        ),
        difficulty=2,
        explicit_facts=(
            "table:orders",
        ),
    )

    result = grounded_contract_recovery(
        requirement,
        grounding=Grounding(
            requirement_id="r3",
            path="shop/repository.py",
            kind="query_layer",
        ),
        workspace=tmp_path,
    )

    assert result.valid
    assert "joinedload(" in result.value
    assert "Order.items" in result.value


def test_recovery_rejects_workspace_escape(
    tmp_path: Path,
):
    outside = (
        tmp_path.parent
        / "outside-grounding-v43.py"
    )

    outside.write_text(
        'session.query("orders").all()\n',
        encoding="utf-8",
    )

    requirement = Requirement(
        requirement_id="r1",
        text=(
            "Analyze slow queries on the orders table"
        ),
        difficulty=2,
        explicit_facts=(
            "table:orders",
        ),
    )

    result = grounded_contract_recovery(
        requirement,
        grounding=Grounding(
            requirement_id="r1",
            path="../outside-grounding-v43.py",
            kind="query_layer",
        ),
        workspace=tmp_path,
    )

    assert not result.valid
    assert (
        "escaped workspace"
        in result.detail
    )
