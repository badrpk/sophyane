from __future__ import annotations

from pathlib import Path

import pytest

from sophyane.task_compiler import (
    Requirement,
    compile_task,
    requirement_contract,
)

from sophyane.task_executor import (
    executor_catalog,
)


CASES = (
    (
        "cache_stampede",
        (
            "Implement protection against cache stampede around a "
            "database-backed product lookup using single-flight locking, "
            "bounded stale serving, and safe fallback behavior."
        ),
    ),
    (
        "idempotency_key",
        (
            "Add idempotency-key handling to a payment API so repeated "
            "POST requests with the same key cannot charge twice and "
            "return the original response safely."
        ),
    ),
    (
        "transactional_outbox",
        (
            "Replace direct event publication after database writes "
            "with a transactional outbox pattern so the state change "
            "and event record commit atomically, then publish using "
            "a retrying background worker with duplicate protection."
        ),
    ),
    (
        "saga_compensation",
        (
            "Implement a payment-and-inventory saga for checkout with "
            "explicit compensation if payment succeeds but inventory "
            "reservation fails, including durable state transitions."
        ),
    ),
)


@pytest.mark.parametrize(
    "contract,prompt",
    CASES,
)
def test_v62_contract_classification(
    contract: str,
    prompt: str,
):
    requirement = Requirement(
        requirement_id="r1",
        text=prompt,
        difficulty=5,
        explicit_facts=(
            "architecture:"
            + contract,
        ),
    )

    assert (
        requirement_contract(
            requirement
        )
        == contract
    )


def _write_fixture(
    root: Path,
    contract: str,
) -> None:
    app = (
        root
        / "app"
    )

    app.mkdir(
        parents=True,
        exist_ok=True,
    )

    if contract == "cache_stampede":
        (
            app
            / "products.py"
        ).write_text(
            """
def get_product(cache, database, product_id):
    cached = cache.get(product_id)
    if cached is not None:
        return cached
    product = database.get_product(product_id)
    cache.set(product_id, product)
    return product
""".strip()
            + "\n",
            encoding="utf-8",
        )

    elif contract == "idempotency_key":
        (
            app
            / "payments.py"
        ).write_text(
            """
def post_payment(request, payment_gateway):
    return payment_gateway.charge(request["amount"])
""".strip()
            + "\n",
            encoding="utf-8",
        )

    elif contract == "transactional_outbox":
        (
            app
            / "orders.py"
        ).write_text(
            """
def save_order(session, broker, order):
    session.add(order)
    session.commit()
    broker.publish("OrderPlaced", {"order_id": order.id})
""".strip()
            + "\n",
            encoding="utf-8",
        )

    elif contract == "saga_compensation":
        (
            app
            / "checkout.py"
        ).write_text(
            """
def checkout(payment_service, inventory_service, order):
    payment = payment_service.charge(order.total)
    inventory = inventory_service.reserve(order.items)
    return payment, inventory
""".strip()
            + "\n",
            encoding="utf-8",
        )


@pytest.mark.parametrize(
    "contract,prompt",
    CASES,
)
def test_v62_raw_parent_is_one_complete_typed_plan(
    tmp_path: Path,
    contract: str,
    prompt: str,
):
    _write_fixture(
        tmp_path,
        contract,
    )

    result = compile_task(
        prompt,
        workspace=tmp_path,
    )

    assert result.handled
    assert result.ok
    assert result.unresolved == []

    assert len(
        result.requirements
    ) == 1

    assert len(
        result.execution_plan
    ) == 1

    step = result.execution_plan[
        0
    ]

    assert (
        step["contract"]
        == contract
    )

    assert step[
        "targets"
    ]


def test_v62_executor_authority_boundary_after_c3():
    catalog = set(
        executor_catalog()
    )

    assert catalog == {
        "database_analysis",
        "database_index",
        "orm_eager_fetch",
        "circuit_breaker",
        "async_event",
        "idempotency_key",
        "cache_stampede",
        "transactional_outbox",
        "saga_compensation",
        "redis_sliding_window_rate_limit",
    }
