from __future__ import annotations

from pathlib import Path

from sophyane.task_compiler import (
    estimate_difficulty,
    should_compile,
)

from sophyane.unified_execution_kernel import (
    _bounded_deterministic_reasoning,
    execute_request,
)


def test_arithmetic_fallback():
    value = _bounded_deterministic_reasoning(
        "If a worker processes 12 items per minute, "
        "how many items are processed in 5 minutes?"
    )

    assert value is not None
    assert "60" in value


def test_git_rebase_fallback():
    value = _bounded_deterministic_reasoning(
        "In one sentence, explain what git rebase does."
    )

    assert value is not None
    assert "commit" in value.lower()
    assert "base" in value.lower()


def test_sql_transaction_fallback():
    value = _bounded_deterministic_reasoning(
        "Give one concise SQL transaction pattern that transfers "
        "money between two accounts safely with rollback on failure."
    )

    assert value is not None

    lower = value.lower()

    assert "begin" in lower
    assert "commit" in lower
    assert "rollback" in lower
    assert "update" in lower


def test_token_bucket_fallback():
    value = _bounded_deterministic_reasoning(
        "Give one concise token-bucket rate-limiting policy "
        "for 100 requests per minute with burst capacity 20."
    )

    assert value is not None

    lower = value.lower()

    assert "100" in lower
    assert "20" in lower
    assert "token" in lower


def test_cache_stampede_is_hard():
    text = (
        "Implement protection against cache stampede around a "
        "database-backed product lookup using single-flight locking, "
        "bounded stale serving, and safe fallback behavior."
    )

    assert estimate_difficulty(
        text
    ) >= 3

    assert should_compile(
        text
    )


def test_idempotency_is_hard():
    text = (
        "Add idempotency-key handling to a payment API so repeated "
        "POST requests with the same key cannot charge twice and "
        "return the original response safely."
    )

    assert estimate_difficulty(
        text
    ) >= 3

    assert should_compile(
        text
    )


def test_outbox_is_hard():
    text = (
        "Replace direct event publication after database writes "
        "with a transactional outbox pattern so state and event "
        "commit atomically with retry and duplicate protection."
    )

    assert estimate_difficulty(
        text
    ) >= 3

    assert should_compile(
        text
    )


def test_saga_is_hard():
    text = (
        "Implement a payment-and-inventory saga for checkout with "
        "explicit compensation and durable state transitions."
    )

    assert estimate_difficulty(
        text
    ) >= 3

    assert should_compile(
        text
    )


def test_arithmetic_routes_successfully():
    result = execute_request(
        "If a worker processes 12 items per minute, "
        "how many items are processed in 5 minutes?",
        workspace=Path.cwd(),
        request_id="v62-arithmetic",
    )

    assert result is not None
    assert result.handled
    assert result.ok
    assert "60" in result.output


def test_git_rebase_routes_successfully():
    result = execute_request(
        "In one sentence, explain what git rebase does.",
        workspace=Path.cwd(),
        request_id="v62-rebase",
    )

    assert result is not None
    assert result.handled
    assert result.ok
    assert "commit" in result.output.lower()
