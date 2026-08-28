from __future__ import annotations

from pathlib import Path

from sophyane.task_compiler import (
    Requirement,
    ground_requirement,
    infer_objective_context,
)


def test_parent_objective_extracts_orders_domain():
    context = infer_objective_context(
        "Analyze slow queries on the orders table. "
        "Rewrite N+1 ORM queries."
    )

    assert context["table"] == "orders"


def test_generic_select_on_users_is_not_orders_grounding(
    tmp_path: Path,
):
    path = tmp_path / "users.py"

    path.write_text(
        "rows = db.execute("
        "'SELECT * FROM users WHERE status = 1'"
        ")\n",
        encoding="utf-8",
    )

    requirement = Requirement(
        requirement_id="r1",
        text=(
            "Analyze slow queries generating high DB CPU load"
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


def test_generic_users_index_is_not_orders_grounding(
    tmp_path: Path,
):
    path = tmp_path / "users.sql"

    path.write_text(
        "CREATE TABLE users(id INTEGER, email TEXT);\n"
        "CREATE INDEX idx_users_email ON users(email);\n",
        encoding="utf-8",
    )

    requirement = Requirement(
        requirement_id="r2",
        text=(
            "Add composite index "
            "(user_id, status, created_at)"
        ),
        difficulty=3,
        explicit_facts=(
            "table:orders",
        ),
    )

    assert ground_requirement(
        requirement,
        workspace=tmp_path,
    ) == []


def test_same_domain_order_model_is_grounded(
    tmp_path: Path,
):
    model = (
        tmp_path
        / "models"
        / "order.py"
    )

    model.parent.mkdir()

    model.write_text(
        "class Order:\n"
        "    __tablename__ = 'orders'\n"
        "    user_id = Column(Integer)\n"
        "    status = Column(String)\n"
        "    created_at = Column(DateTime)\n",
        encoding="utf-8",
    )

    requirement = Requirement(
        requirement_id="r2",
        text=(
            "Add composite index "
            "(user_id, status, created_at)"
        ),
        difficulty=3,
        explicit_facts=(
            "table:orders",
        ),
    )

    refs = ground_requirement(
        requirement,
        workspace=tmp_path,
    )

    assert refs
    assert refs[0].path == "models/order.py"


def test_eager_loading_users_does_not_ground_orders(
    tmp_path: Path,
):
    path = (
        tmp_path
        / "repositories"
        / "users.py"
    )

    path.parent.mkdir()

    path.write_text(
        "query = session.query(User).options("
        "joinedload(User.roles)"
        ")\n",
        encoding="utf-8",
    )

    requirement = Requirement(
        requirement_id="r3",
        text=(
            "rewrite N+1 ORM queries "
            "using eager loading"
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
