from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

from sophyane.task_compiler import compile_task
from sophyane.task_executor import (
    execute_compiled_task,
    executor_catalog,
)


PROMPT = (
    "Replace direct event publication after database writes "
    "with a transactional outbox pattern so the state change "
    "and event record commit atomically, then publish using "
    "a retrying background worker with duplicate protection."
)


def _write(
    root: Path,
    *,
    include_broker: bool = True,
) -> Path:
    path = (
        root
        / "app"
        / "orders.py"
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    broker_arg = (
        "    broker,\n"
        if include_broker
        else ""
    )

    publish = (
        '''
    broker.publish(
        "OrderPlaced",
        {
            "order_id": order.id,
        },
    )
'''
        if include_broker
        else ""
    )

    path.write_text(
        (
            "def save_order(\n"
            "    session,\n"
            + broker_arg
            + "    order,\n"
            "):\n"
            "    session.add(order)\n"
            "    session.commit()\n"
            + publish
        ),
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
        "redis_sliding_window_rate_limit",
    }




def test_raw_outbox_prompt_mutates(
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

    result = execute_compiled_task(
        compiled,
        workspace=tmp_path,
    )

    assert result.ok
    assert result.steps
    assert result.steps[0].mutated

    text = path.read_text()

    assert (
        "SOPHYANE_TRANSACTIONAL_OUTBOX_V1"
        in text
    )

    assert "outbox_event" in text
    assert "publish_pending_outbox" in text


def test_outbox_executor_is_idempotent(
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

    before = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()

    compiled_again = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    second = execute_compiled_task(
        compiled_again,
        workspace=tmp_path,
    )

    after = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()

    assert second.ok
    assert not second.steps[0].mutated
    assert before == after


def test_outbox_fails_closed_without_broker(
    tmp_path: Path,
):
    path = _write(
        tmp_path,
        include_broker=False,
    )

    before = path.read_bytes()

    compiled = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    if not compiled.ok:
        assert path.read_bytes() == before
        return

    result = execute_compiled_task(
        compiled,
        workspace=tmp_path,
    )

    assert not result.ok
    assert result.steps
    assert not result.steps[0].mutated
    assert path.read_bytes() == before


def test_outbox_behavior(
    tmp_path: Path,
):
    path = _write(
        tmp_path
    )

    compiled = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    result = execute_compiled_task(
        compiled,
        workspace=tmp_path,
    )

    assert result.ok

    spec = (
        importlib.util.spec_from_file_location(
            "outbox_fixture",
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

    class Order:
        id = 17

    class Session:
        def __init__(self):
            self.added = []
            self.commits = 0

        def add(
            self,
            value,
        ):
            self.added.append(
                value
            )

        def commit(
            self,
        ):
            self.commits += 1

    class Broker:
        def __init__(self):
            self.calls = []

        def publish(
            self,
            event_type,
            payload,
            *,
            event_id,
        ):
            self.calls.append(
                (
                    event_type,
                    payload,
                    event_id,
                )
            )

    session = Session()
    broker = Broker()
    order = Order()

    outbox = module.save_order(
        session,
        broker,
        order,
    )

    assert session.commits == 1

    assert len(
        session.added
    ) == 2

    assert session.added[0] is order
    assert session.added[1] is outbox

    # No direct publication occurs in the transaction path.
    assert broker.calls == []

    first = module.publish_pending_outbox(
        [outbox],
        broker=broker,
    )

    assert first == [
        outbox["event_id"]
    ]

    assert len(
        broker.calls
    ) == 1

    assert outbox[
        "published"
    ] is True

    # Duplicate worker pass is safe.
    second = module.publish_pending_outbox(
        [outbox],
        broker=broker,
    )

    assert second == []
    assert len(
        broker.calls
    ) == 1


def test_saga_still_unregistered():
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
