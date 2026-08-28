from __future__ import annotations

from sophyane.task_compiler import (
    Requirement,
    requirement_contract,
    validate_requirement_evidence,
)


def req(text: str) -> Requirement:
    return Requirement(
        requirement_id="r1",
        text=text,
        difficulty=2,
    )


def test_database_analysis_requires_diagnostic_artifact():
    requirement = req(
        "Analyze slow queries on the orders table generating high DB CPU load"
    )

    assert (
        requirement_contract(requirement)
        == "database_analysis"
    )

    valid, _ = validate_requirement_evidence(
        requirement,
        "Analyze the slow queries and optimize the database.",
    )

    assert not valid

    valid, _ = validate_requirement_evidence(
        requirement,
        "EXPLAIN ANALYZE SELECT * FROM orders WHERE user_id = ?;",
    )

    assert valid


def test_database_index_rejects_requirement_restatement():
    requirement = req(
        "Add composite index on "
        "(user_id, status, created_at) to optimize pagination"
    )

    valid, _ = validate_requirement_evidence(
        requirement,
        "Add a composite index on "
        "(user_id, status, created_at) to optimize pagination.",
    )

    assert not valid


def test_database_index_accepts_concrete_sql():
    requirement = req(
        "Add composite index on "
        "(user_id, status, created_at) to optimize pagination"
    )

    valid, _ = validate_requirement_evidence(
        requirement,
        "CREATE INDEX idx_orders_user_status_created "
        "ON orders (user_id, status, created_at);",
    )

    assert valid


def test_index_column_order_is_verified():
    requirement = req(
        "Add composite index on "
        "(user_id, status, created_at)"
    )

    valid, _ = validate_requirement_evidence(
        requirement,
        "CREATE INDEX idx_bad "
        "ON orders (status, user_id, created_at);",
    )

    assert not valid


def test_n_plus_one_requires_executable_looking_shape():
    requirement = req(
        "rewrite N+1 ORM queries using explicit JOIN FETCH / eager_load"
    )

    valid, _ = validate_requirement_evidence(
        requirement,
        "Use explicit JOIN FETCH / eager_load in your ORM queries.",
    )

    assert not valid


def test_n_plus_one_accepts_concrete_join_fetch():
    requirement = req(
        "rewrite N+1 ORM queries using explicit JOIN FETCH / eager_load"
    )

    valid, _ = validate_requirement_evidence(
        requirement,
        "SELECT o FROM Order o "
        "JOIN FETCH o.items "
        "WHERE o.user.id = :user_id",
    )

    assert valid


def test_n_plus_one_accepts_concrete_joinedload():
    requirement = req(
        "rewrite N+1 ORM queries using eager loading"
    )

    valid, _ = validate_requirement_evidence(
        requirement,
        "session.query(Order).options("
        "joinedload(Order.items)).all()",
    )

    assert valid


def test_index_name_words_do_not_corrupt_column_order_validation():
    requirement = req(
        "Add composite index on "
        "(user_id, status, created_at)"
    )

    valid, detail = validate_requirement_evidence(
        requirement,
        "CREATE INDEX idx_status_created_user "
        "ON orders (user_id, status, created_at);",
    )

    assert valid, detail


def test_index_column_order_still_rejects_real_reordering():
    requirement = req(
        "Add composite index on "
        "(user_id, status, created_at)"
    )

    valid, detail = validate_requirement_evidence(
        requirement,
        "CREATE INDEX idx_orders "
        "ON orders (status, user_id, created_at);",
    )

    assert not valid
    assert "ordering" in detail


def test_index_missing_requested_column_is_rejected():
    requirement = req(
        "Add composite index on "
        "(user_id, status, created_at)"
    )

    valid, detail = validate_requirement_evidence(
        requirement,
        "CREATE INDEX idx_orders "
        "ON orders (user_id, status);",
    )

    assert not valid
    assert "omitted" in detail
