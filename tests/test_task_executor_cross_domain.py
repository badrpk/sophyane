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


def test_cross_domain_executors_registered():
    assert set(
        executor_catalog()
    ) >= {
        "circuit_breaker",
        "async_event",
    }


def test_circuit_breaker_executor(
    tmp_path: Path,
):
    app = tmp_path / "app"
    app.mkdir()

    source = app / "payments.py"

    source.write_text(
        """
def primary_payment_gateway(payload):
    return payload


def secondary_payment_processor(payload):
    return payload
""",
        encoding="utf-8",
    )

    requirement = Requirement(
        requirement_id="r1",
        text=(
            "Integrate circuit breaker around primary payment "
            "gateway. Open after 5 consecutive 5xx or timeout "
            "failures within 30 seconds and fall back to secondary."
        ),
        difficulty=5,
    )

    compiled = CompiledTask(
        handled=True,
        ok=True,
        difficulty=5,
        requirements=[
            requirement
        ],
        evidence={
            "r1": Evidence(
                value=(
                    "Circuit breaker opens after 5 consecutive "
                    "HTTP 5xx or timeout failures within 30 seconds "
                    "and uses secondary fallback."
                ),
                provenance="TEST",
                valid=True,
            )
        },
        groundings={
            "r1": [
                Grounding(
                    requirement_id="r1",
                    path="app/payments.py",
                    kind="source",
                )
            ]
        },
        execution_plan=[
            {
                "requirement_id": "r1",
                "contract": "circuit_breaker",
                "operation": "modify_http_client",
                "validated_value": (
                    "Open after 5 consecutive 5xx or timeout "
                    "failures within 30 seconds; fallback secondary."
                ),
                "targets": [
                    {
                        "path": "app/payments.py",
                        "kind": "source",
                    }
                ],
                "dry_run": True,
            }
        ],
    )

    result = execute_compiled_task(
        compiled,
        workspace=tmp_path,
    )

    assert result.ok

    text = source.read_text().lower()
    compact = text.replace(" ", "")

    assert "classpaymentcircuitbreaker" in compact
    assert "threshold=5" in compact
    assert "window_seconds=30.0" in compact


def test_async_event_executor(
    tmp_path: Path,
):
    app = tmp_path / "app"
    app.mkdir()

    source = app / "checkout.py"

    source.write_text(
        """def checkout(
    order,
    *,
    send_email,
    log_analytics,
    update_inventory,
):
    send_email(order)
    log_analytics(order)
    update_inventory(order)

    return order
""",
        encoding="utf-8",
    )

    requirement = Requirement(
        requirement_id="r1",
        text=(
            "Publish OrderPlaced and move email analytics "
            "and inventory into asynchronous consumers."
        ),
        difficulty=5,
    )

    compiled = CompiledTask(
        handled=True,
        ok=True,
        difficulty=5,
        requirements=[
            requirement
        ],
        evidence={
            "r1": Evidence(
                value=(
                    "Publish OrderPlaced through Kafka producer and "
                    "consume with email analytics inventory consumers."
                ),
                provenance="TEST",
                valid=True,
            )
        },
        groundings={
            "r1": [
                Grounding(
                    requirement_id="r1",
                    path="app/checkout.py",
                    kind="source",
                )
            ]
        },
        execution_plan=[
            {
                "requirement_id": "r1",
                "contract": "async_event",
                "operation": "modify_event_pipeline",
                "validated_value": (
                    "Publish OrderPlaced using Kafka producer "
                    "and asynchronous consumers."
                ),
                "targets": [
                    {
                        "path": "app/checkout.py",
                        "kind": "source",
                    }
                ],
                "dry_run": True,
            }
        ],
    )

    result = execute_compiled_task(
        compiled,
        workspace=tmp_path,
    )

    assert result.ok

    text = source.read_text().lower()

    assert "orderplaced" in text
    assert "broker.publish" in text
    assert "email_consumer" in text
    assert "analytics_consumer" in text
    assert "inventory_consumer" in text
