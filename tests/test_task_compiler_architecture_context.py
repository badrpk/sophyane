from __future__ import annotations

from pathlib import Path

from sophyane.task_compiler import (
    _architecture_groundings,
    _architecture_requirements,
    decompose,
    requirement_contract,
)


CB = (
    "Integrate a circuit breaker around the primary payment "
    "gateway HTTP client. Set the threshold to open after "
    "5 consecutive HTTP 5xx errors or timeouts within a "
    "30 second window, falling back to the secondary "
    "payment processor."
)

AE = (
    "Decouple post-checkout actions from the synchronous HTTP "
    "request thread. Publish an OrderPlaced event to Kafka or "
    "RabbitMQ and migrate email sending, analytics logging, "
    "and inventory updates into dedicated asynchronous "
    "consumer workers."
)


def test_circuit_objective_is_one_typed_parent():
    requirements = _architecture_requirements(
        CB,
        decompose(CB),
    )

    assert len(requirements) == 1
    assert (
        requirement_contract(
            requirements[0]
        )
        == "circuit_breaker"
    )

    text = requirements[0].text.lower()

    assert "5 consecutive" in text
    assert "30 second" in text
    assert "secondary" in text


def test_async_objective_is_one_typed_parent():
    requirements = _architecture_requirements(
        AE,
        decompose(AE),
    )

    assert len(requirements) == 1
    assert (
        requirement_contract(
            requirements[0]
        )
        == "async_event"
    )

    text = requirements[0].text.lower()

    assert "orderplaced" in text
    assert "email" in text
    assert "analytics" in text
    assert "inventory" in text


def test_payment_structure_grounds(
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

    requirement = _architecture_requirements(
        CB,
        decompose(CB),
    )[0]

    refs = _architecture_groundings(
        requirement,
        workspace=tmp_path,
    )

    assert refs
    assert (
        refs[0].path
        == "app/payments.py"
    )


def test_checkout_structure_grounds(
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

    requirement = _architecture_requirements(
        AE,
        decompose(AE),
    )[0]

    refs = _architecture_groundings(
        requirement,
        workspace=tmp_path,
    )

    assert refs
    assert (
        refs[0].path
        == "app/checkout.py"
    )
