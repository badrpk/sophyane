from __future__ import annotations

from concurrent.futures import Future

import pytest

import sophyane.cloud.messaging as messaging


MESSAGE_ID = "wamid.accounting-failure-containment"


def _failed_future() -> Future:
    future = Future()
    future.set_result(
        {
            "ok": False,
            "stage": "dispatch",
        }
    )
    return future


def test_accounting_failure_does_not_strand_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Durable retry accounting is important, but its storage failure must
    not strand process-local admission for an already completed worker.
    """
    released: list[str] = []
    future_done: list[object] = []

    def fail_accounting(message_id: str) -> None:
        assert message_id == MESSAGE_ID
        raise OSError(
            "forced durable retry accounting failure"
        )

    monkeypatch.setattr(
        messaging,
        "_record_whatsapp_inbound_failed_attempt",
        fail_accounting,
    )

    monkeypatch.setattr(
        messaging,
        "_release_whatsapp_inbound_admission",
        released.append,
    )

    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_future_done",
        future_done.append,
    )

    future = _failed_future()

    callback = messaging._whatsapp_inbound_completion_callback(
        MESSAGE_ID
    )

    # Completion cleanup must contain bookkeeping failure. Callback
    # exceptions from background futures must not escape merely because
    # durable attempt accounting failed.
    callback(future)

    assert released == [MESSAGE_ID]
    assert future_done == [future]


def test_accounting_failure_still_runs_future_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    The existing outer finally already protects future/capacity cleanup.
    Keep this as the GREEN control while the admission contract is RED.
    """
    released: list[str] = []
    future_done: list[object] = []

    def fail_accounting(message_id: str) -> None:
        assert message_id == MESSAGE_ID
        raise OSError(
            "forced durable retry accounting failure"
        )

    monkeypatch.setattr(
        messaging,
        "_record_whatsapp_inbound_failed_attempt",
        fail_accounting,
    )

    monkeypatch.setattr(
        messaging,
        "_release_whatsapp_inbound_admission",
        released.append,
    )

    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_future_done",
        future_done.append,
    )

    future = _failed_future()

    callback = messaging._whatsapp_inbound_completion_callback(
        MESSAGE_ID
    )

    callback(future)

    assert released == [MESSAGE_ID]
    assert future_done == [future]
