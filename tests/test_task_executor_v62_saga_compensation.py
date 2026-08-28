from __future__ import annotations

import importlib.util
from pathlib import Path

from sophyane.task_compiler import (
    compile_task,
)

from sophyane.task_executor import (
    execute_compiled_task,
    executor_catalog,
)


PROMPT = (
    "Implement a payment-and-inventory saga for checkout with "
    "explicit compensation if payment succeeds but inventory "
    "reservation fails, including durable state transitions."
)


def _write(
    root: Path,
    *,
    include_store: bool = True,
) -> Path:
    path = (
        root
        / "app"
        / "checkout.py"
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    store_line = (
        "    saga_store,\n"
        if include_store
        else ""
    )

    path.write_text(
        (
            "def checkout(\n"
            "    payment_service,\n"
            "    inventory_service,\n"
            f"{store_line}"
            "    order,\n"
            "):\n"
            "    payment = payment_service.charge(\n"
            "        order.total\n"
            "    )\n"
            "\n"
            "    inventory = inventory_service.reserve(\n"
            "        order.items\n"
            "    )\n"
            "\n"
            "    return payment, inventory\n"
        ),
        encoding="utf-8",
    )

    return path


def test_c4_catalog_is_final():
    assert set(
        executor_catalog()
    ) == {
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


def test_raw_saga_prompt_mutates(
    tmp_path: Path,
):
    path = _write(
        tmp_path
    )

    compiled = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    assert compiled.ok
    assert compiled.unresolved == []

    assert len(
        compiled.execution_plan
    ) == 1

    step = compiled.execution_plan[
        0
    ]

    assert (
        step["contract"]
        == "saga_compensation"
    )

    assert (
        step["operation"]
        == "modify_checkout_orchestration"
    )

    result = execute_compiled_task(
        compiled,
        workspace=tmp_path,
    )

    assert result.ok
    assert result.steps[0].ok
    assert result.steps[0].mutated

    text = path.read_text()

    assert (
        "SOPHYANE_SAGA_COMPENSATION_V1"
        in text
    )

    assert '"PAYMENT_SUCCEEDED"' in text
    assert '"INVENTORY_FAILED"' in text
    assert '"COMPENSATED"' in text
    assert '"COMPLETED"' in text
    assert ".refund(" in text


def test_saga_executor_is_idempotent(
    tmp_path: Path,
):
    path = _write(
        tmp_path
    )

    compiled = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    first = execute_compiled_task(
        compiled,
        workspace=tmp_path,
    )

    assert first.ok
    assert first.steps[0].mutated

    before = path.read_bytes()

    compiled_again = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    second = execute_compiled_task(
        compiled_again,
        workspace=tmp_path,
    )

    assert second.ok
    assert not second.steps[0].mutated
    assert path.read_bytes() == before


def test_saga_fails_closed_without_store(
    tmp_path: Path,
):
    path = _write(
        tmp_path,
        include_store=False,
    )

    before = path.read_bytes()

    compiled = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    assert compiled.ok

    result = execute_compiled_task(
        compiled,
        workspace=tmp_path,
    )

    assert not result.ok
    assert result.steps
    assert not result.steps[0].mutated
    assert path.read_bytes() == before


def _load(
    path: Path,
    name: str,
):
    spec = (
        importlib.util.spec_from_file_location(
            name,
            path,
        )
    )

    assert spec is not None
    assert spec.loader is not None

    module = (
        importlib.util.module_from_spec(
            spec
        )
    )

    spec.loader.exec_module(
        module
    )

    return module


def test_saga_success_and_terminal_replay(
    tmp_path: Path,
):
    path = _write(
        tmp_path
    )

    compiled = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    execution = execute_compiled_task(
        compiled,
        workspace=tmp_path,
    )

    assert execution.ok

    module = _load(
        path,
        "saga_success_fixture",
    )

    class Order:
        id = "order-1"
        total = 500
        items = ["sku-1"]

    class Payment:
        def __init__(self):
            self.charges = []
            self.refunds = []

        def charge(
            self,
            amount,
        ):
            result = {
                "payment_id": "pay-1",
                "amount": amount,
            }

            self.charges.append(
                result
            )

            return result

        def refund(
            self,
            payment,
        ):
            self.refunds.append(
                payment
            )

            return {
                "refund_id": "refund-1",
            }

    class Inventory:
        def __init__(self):
            self.calls = []

        def reserve(
            self,
            items,
        ):
            self.calls.append(
                tuple(items)
            )

            return {
                "reservation_id": "inv-1",
            }

    class Store:
        def __init__(self):
            self.records = {}

        def get(
            self,
            key,
        ):
            return self.records.get(
                key
            )

        def put(
            self,
            key,
            value,
        ):
            self.records[key] = dict(
                value
            )

    payment = Payment()
    inventory = Inventory()
    store = Store()

    first = module.checkout(
        payment,
        inventory,
        store,
        Order(),
    )

    assert first["state"] == "COMPLETED"
    assert len(payment.charges) == 1
    assert payment.refunds == []
    assert len(inventory.calls) == 1

    second = module.checkout(
        payment,
        inventory,
        store,
        Order(),
    )

    assert second["state"] == "COMPLETED"
    assert len(payment.charges) == 1
    assert len(inventory.calls) == 1


def test_saga_inventory_failure_compensates_once(
    tmp_path: Path,
):
    path = _write(
        tmp_path
    )

    compiled = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    execution = execute_compiled_task(
        compiled,
        workspace=tmp_path,
    )

    assert execution.ok

    module = _load(
        path,
        "saga_failure_fixture",
    )

    class Order:
        id = "order-2"
        total = 700
        items = ["sku-x"]

    class Payment:
        def __init__(self):
            self.charges = []
            self.refunds = []

        def charge(
            self,
            amount,
        ):
            result = {
                "payment_id": "pay-2",
                "amount": amount,
            }

            self.charges.append(
                result
            )

            return result

        def refund(
            self,
            payment,
        ):
            self.refunds.append(
                payment
            )

            return {
                "refund_id": "refund-2",
            }

    class Inventory:
        def reserve(
            self,
            items,
        ):
            raise RuntimeError(
                "inventory unavailable"
            )

    class Store:
        def __init__(self):
            self.records = {}
            self.history = []

        def get(
            self,
            key,
        ):
            return self.records.get(
                key
            )

        def put(
            self,
            key,
            value,
        ):
            snapshot = dict(
                value
            )

            self.records[key] = snapshot
            self.history.append(
                snapshot
            )

    payment = Payment()
    inventory = Inventory()
    store = Store()

    first = module.checkout(
        payment,
        inventory,
        store,
        Order(),
    )

    assert first["state"] == "COMPENSATED"
    assert len(payment.charges) == 1
    assert len(payment.refunds) == 1

    states = [
        item["state"]
        for item in store.history
    ]

    assert states == [
        "STARTED",
        "PAYMENT_SUCCEEDED",
        "INVENTORY_FAILED",
        "COMPENSATED",
    ]

    second = module.checkout(
        payment,
        inventory,
        store,
        Order(),
    )

    assert second["state"] == "COMPENSATED"
    assert len(payment.charges) == 1
    assert len(payment.refunds) == 1
