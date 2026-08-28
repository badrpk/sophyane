from __future__ import annotations

from sophyane.task_compiler import (
    Requirement,
    recursive_children,
    validate_requirement_evidence,
)


def req(text: str) -> Requirement:
    return Requirement(
        requirement_id="r1",
        text=text,
        difficulty=3,
    )


def test_wrong_index_table_is_rejected():
    requirement = req(
        "Add composite index on the orders table "
        "(user_id, status, created_at)"
    )

    valid, detail = validate_requirement_evidence(
        requirement,
        "CREATE INDEX idx_orders "
        "ON user (user_id, status, created_at);",
    )

    assert not valid
    assert "wrong table" in detail


def test_correct_index_table_is_accepted():
    requirement = req(
        "Add composite index on the orders table "
        "(user_id, status, created_at)"
    )

    valid, detail = validate_requirement_evidence(
        requirement,
        "CREATE INDEX idx_orders "
        "ON orders (user_id, status, created_at);",
    )

    assert valid, detail


def test_database_analysis_has_recursive_children():
    children = recursive_children(
        req(
            "Analyze slow queries on the orders table "
            "generating high DB CPU load"
        )
    )

    assert len(children) == 2
    assert all(
        child.difficulty <= 2
        for child in children
    )


def test_n_plus_one_has_recursive_children():
    children = recursive_children(
        req(
            "rewrite N+1 ORM queries using explicit "
            "JOIN FETCH / eager_load"
        )
    )

    assert len(children) == 2
    assert all(
        child.difficulty <= 2
        for child in children
    )
