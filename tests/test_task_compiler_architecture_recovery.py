from __future__ import annotations

from pathlib import Path

from sophyane.task_compiler import (
    Grounding,
    Requirement,
    grounded_contract_recovery,
)


def test_circuit_breaker_grounded_recovery(
    tmp_path: Path,
):
    target = (
        tmp_path
        / "app"
        / "payments.py"
    )

    target.parent.mkdir(
        parents=True
    )

    target.write_text(
        """
class PrimaryPaymentGateway:
    def charge(self, payload):
        return payload


class SecondaryPaymentProcessor:
    def charge(self, payload):
        return payload


def process_payment(payload, primary, secondary):
    return primary.charge(payload)
""",
        encoding="utf-8",
    )

    requirement = Requirement(
        requirement_id="r1",
        text=(
            "Integrate a circuit breaker around the primary payment "
            "gateway HTTP client. Set the threshold to open after "
            "5 consecutive HTTP 5xx errors or timeouts within a "
            "30 second window, falling back to the secondary "
            "payment processor."
        ),
        difficulty=3,
        explicit_facts=(
            "5",
            "30",
            "architecture:circuit_breaker",
        ),
    )

    evidence = grounded_contract_recovery(
        requirement,
        grounding=Grounding(
            requirement_id="r1",
            path="app/payments.py",
            kind="service_or_client",
        ),
        workspace=tmp_path,
    )

    assert evidence.valid
    assert (
        evidence.provenance
        == "GROUNDED_DETERMINISTIC"
    )

    lower = evidence.value.lower()

    assert "5 consecutive" in lower
    assert "30 seconds" in lower
    assert "5xx" in lower
    assert "timeout" in lower
    assert "secondary" in lower
    assert "open" in lower


def test_async_event_grounded_recovery(
    tmp_path: Path,
):
    target = (
        tmp_path
        / "app"
        / "checkout.py"
    )

    target.parent.mkdir(
        parents=True
    )

    target.write_text(
        """
def checkout(
    order,
    send_email,
    log_analytics,
    update_inventory,
):
    send_email(order)
    log_analytics(order)
    update_inventory(order)
""",
        encoding="utf-8",
    )

    requirement = Requirement(
        requirement_id="r1",
        text=(
            "Decouple post-checkout actions from the synchronous "
            "HTTP request thread. Publish an OrderPlaced event to "
            "Kafka or RabbitMQ and migrate email sending, analytics "
            "logging, and inventory updates into dedicated "
            "asynchronous consumer workers."
        ),
        difficulty=3,
        explicit_facts=(
            "OrderPlaced",
            "architecture:async_event",
        ),
    )

    evidence = grounded_contract_recovery(
        requirement,
        grounding=Grounding(
            requirement_id="r1",
            path="app/checkout.py",
            kind="service_or_client",
        ),
        workspace=tmp_path,
    )

    assert evidence.valid
    assert (
        evidence.provenance
        == "GROUNDED_DETERMINISTIC"
    )

    lower = evidence.value.lower()

    assert "orderplaced" in lower
    assert "publish" in lower
    assert "email consumer" in lower
    assert "analytics consumer" in lower
    assert "inventory consumer" in lower
