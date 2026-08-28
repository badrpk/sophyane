from __future__ import annotations

from pathlib import Path

from sophyane.task_compiler import (
    Requirement,
    ground_requirement,
)


def test_query_string_proves_orders_domain(
    tmp_path: Path,
):
    path = (
        tmp_path
        / "shop"
        / "repository.py"
    )

    path.parent.mkdir(
        parents=True
    )

    path.write_text(
        'rows = session.query("orders").filter_by('
        'user_id=user_id).all()\n',
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

    refs = ground_requirement(
        requirement,
        workspace=tmp_path,
    )

    assert refs

    assert any(
        ref.path
        == "shop/repository.py"
        for ref in refs
    )


def test_same_domain_n_plus_one_problem_is_grounded(
    tmp_path: Path,
):
    path = (
        tmp_path
        / "shop"
        / "repository.py"
    )

    path.parent.mkdir(
        parents=True
    )

    path.write_text(
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

    refs = ground_requirement(
        requirement,
        workspace=tmp_path,
    )

    assert refs

    matching = [
        ref
        for ref in refs
        if ref.path
        == "shop/repository.py"
    ]

    assert matching

    assert any(
        "n-plus-one-problem-site"
        in ref.evidence
        for ref in matching
    )


def test_users_n_plus_one_is_not_orders_grounding(
    tmp_path: Path,
):
    path = (
        tmp_path
        / "shop"
        / "users.py"
    )

    path.parent.mkdir(
        parents=True
    )

    path.write_text(
        '''
def load_users(session):
    users = session.query("users").all()

    for user in users:
        session.query("roles").filter_by(
            user_id=user.id
        ).all()
''',
        encoding="utf-8",
    )

    requirement = Requirement(
        requirement_id="r3",
        text=(
            "rewrite N+1 ORM queries using eager loading"
        ),
        difficulty=2,
        explicit_facts=(
            "table:orders",
        ),
    )

    assert ground_requirement(
        requirement,
        workspace=tmp_path,
    ) == []
