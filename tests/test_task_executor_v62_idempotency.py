from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sophyane.task_compiler import (
    Requirement,
)
from sophyane.task_executor import (
    execute_compiled_task,
    executor_catalog,
)


def _requirement():
    return Requirement(
        requirement_id="r1",
        text=(
            "Add idempotency-key handling to a payment API "
            "so repeated POST requests with the same key "
            "cannot charge twice and return the original response."
        ),
        difficulty=4,
        explicit_facts=(
            "architecture:idempotency_key",
        ),
    )


def _compiled():
    return SimpleNamespace(
        ok=True,
        requirements=[
            _requirement(),
        ],
        execution_plan=[
            {
                "requirement_id": "r1",
                "contract": "idempotency_key",
                "operation": "modify_payment_handler",
                "validated_value": (
                    "Persist the Idempotency-Key and request "
                    "fingerprint, store the original response, "
                    "and replay duplicate requests without "
                    "charging twice."
                ),
                "targets": [
                    {
                        "path": "app/payments.py",
                    }
                ],
            }
        ],
    )


def _good_fixture(
    root: Path,
):
    path = (
        root
        / "app"
        / "payments.py"
    )

    path.parent.mkdir(
        parents=True
    )

    path.write_text(
        """
class PersistentIdempotencyStore:
    def __init__(self):
        self.records = {}

    def get(self, key):
        return self.records.get(key)

    def put(self, key, value):
        self.records[key] = value


class PaymentGateway:
    def charge(self, amount):
        return {"amount": amount}


def post_payment(request, payment_gateway, idempotency_store):
    result = payment_gateway.charge(request["amount"])
    return {"status": 201, "payment": result}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    return path


def test_c3_catalog_is_exact():
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
    }


def test_c1_mutates_proven_shape(
    tmp_path: Path,
):
    path = _good_fixture(
        tmp_path
    )

    result = execute_compiled_task(
        _compiled(),
        workspace=tmp_path,
    )

    assert result.ok
    assert result.steps[0].ok
    assert result.steps[0].mutated

    text = path.read_text()

    assert (
        "SOPHYANE_IDEMPOTENCY_KEY_V1"
        in text
    )
    assert "fingerprint" in text
    assert "original_response" in text
    assert ".put(" in text

    compile(
        text,
        str(path),
        "exec",
    )


def test_c1_repeat_is_idempotent(
    tmp_path: Path,
):
    path = _good_fixture(
        tmp_path
    )

    first = execute_compiled_task(
        _compiled(),
        workspace=tmp_path,
    )

    assert first.ok
    assert first.steps[0].mutated

    before = path.read_bytes()

    second = execute_compiled_task(
        _compiled(),
        workspace=tmp_path,
    )

    assert second.ok
    assert not second.steps[0].mutated
    assert path.read_bytes() == before


def test_c1_requires_explicit_store_dependency(
    tmp_path: Path,
):
    path = (
        tmp_path
        / "app"
        / "payments.py"
    )

    path.parent.mkdir(
        parents=True
    )

    original = (
        "def post_payment(request, payment_gateway):\n"
        "    return payment_gateway.charge(request['amount'])\n"
    )

    path.write_text(
        original,
        encoding="utf-8",
    )

    result = execute_compiled_task(
        _compiled(),
        workspace=tmp_path,
    )

    assert not result.ok
    assert not result.steps[0].mutated
    assert path.read_text() == original


def test_post_c3_remaining_families_still_unregistered():
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
    }
