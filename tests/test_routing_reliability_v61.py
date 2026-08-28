from __future__ import annotations

from pathlib import Path

from sophyane.task_compiler import (
    Grounding,
    Requirement,
    grounded_contract_recovery,
)
from sophyane.unified_execution_kernel import (
    execute_request,
)


def test_http_status_meaning_is_canonical():
    result = execute_request(
        "Explain in one short sentence what HTTP 429 means.",
        workspace=Path.cwd(),
        request_id="v61-http-429",
    )

    assert result is not None
    assert result.handled
    assert result.ok
    assert (
        result.capability
        == "reasoning.direct_local"
    )

    lower = result.output.lower()

    assert "429" in lower
    assert "too many requests" in lower


def test_grounded_index_recovery_uses_user_table_and_order(
    tmp_path: Path,
):
    schema = (
        tmp_path
        / "migrations"
        / "001_create_orders.sql"
    )

    schema.parent.mkdir(
        parents=True
    )

    schema.write_text(
        "CREATE TABLE orders ("
        "user_id INTEGER, "
        "status TEXT, "
        "created_at TIMESTAMP"
        ");",
        encoding="utf-8",
    )

    requirement = Requirement(
        requirement_id="r2",
        text=(
            "Add composite index on the orders table "
            "(user_id, status, created_at)"
        ),
        difficulty=3,
        explicit_facts=(
            "user_id",
            "table:orders",
        ),
    )

    grounding = Grounding(
        requirement_id="r2",
        path="migrations/001_create_orders.sql",
        kind="migration_or_sql",
        score=20.0,
        evidence="domain:create-table",
    )

    result = grounded_contract_recovery(
        requirement,
        grounding=grounding,
        workspace=tmp_path,
    )

    assert result.valid
    assert (
        result.provenance
        == "GROUNDED_DETERMINISTIC"
    )

    lower = result.value.lower()

    assert "create index" in lower
    assert "on orders" in lower

    positions = [
        lower.index(
            token
        )
        for token in (
            "user_id",
            "status",
            "created_at",
        )
    ]

    assert positions == sorted(
        positions
    )


def test_bounded_backoff_fallback_is_contract_correct():
    from sophyane.unified_execution_kernel import (
        _bounded_deterministic_reasoning,
    )

    result = _bounded_deterministic_reasoning(
        "Give one concise exponential-backoff retry policy "
        "with maximum 3 retries."
    )

    assert result is not None

    lower = result.lower()

    assert "exponential backoff" in lower
    assert "3 retries" in lower
    assert "1s" in lower
    assert "2s" in lower
    assert "4s" in lower


def test_bounded_fallback_does_not_claim_unknown_tasks():
    from sophyane.unified_execution_kernel import (
        _bounded_deterministic_reasoning,
    )

    assert (
        _bounded_deterministic_reasoning(
            "Design an entirely new distributed database."
        )
        is None
    )
