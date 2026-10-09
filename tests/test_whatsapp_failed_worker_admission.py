from __future__ import annotations

import inspect

import pytest

import sophyane.cloud.messaging as messaging


class ControlledFuture:
    def __init__(self):
        self.callback = None
        self._result = None
        self._exception = None

    def add_done_callback(self, callback):
        self.callback = callback

    def result(self):
        if self._exception is not None:
            raise self._exception
        return self._result

    def exception(self):
        return self._exception

    def complete_result(self, result):
        self._result = result
        assert self.callback is not None
        self.callback(self)

    def complete_exception(self, exc):
        self._exception = exc
        assert self.callback is not None
        self.callback(self)


class ControlledExecutor:
    def __init__(self):
        self.submissions = []
        self.futures = []

    def submit(self, fn, message):
        future = ControlledFuture()
        self.submissions.append(
            (fn, dict(message))
        )
        self.futures.append(future)
        return future


@pytest.fixture
def isolated_worker(monkeypatch, tmp_path):
    spool = tmp_path / "inbound"
    executor = ControlledExecutor()

    monkeypatch.setattr(
        messaging,
        "WHATSAPP_INBOUND_SPOOL",
        spool,
    )
    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_executor",
        executor,
    )

    messaging._reset_whatsapp_inbound_admission_for_tests()
    messaging._reset_whatsapp_inbound_capacity_for_tests()
    messaging._reset_whatsapp_inbound_idempotency_for_tests()
    messaging._whatsapp_inbound_futures.clear()

    yield spool, executor

    messaging._reset_whatsapp_inbound_admission_for_tests()
    messaging._reset_whatsapp_inbound_capacity_for_tests()
    messaging._reset_whatsapp_inbound_idempotency_for_tests()
    messaging._whatsapp_inbound_futures.clear()


def _message(message_id="wamid.worker-failure"):
    return {
        "message_id": message_id,
        "sender": "923001234567",
        "text": "hello",
    }


def test_failed_worker_result_releases_handoff_admission(
    isolated_worker,
):
    spool, executor = isolated_worker
    message = _message()

    queued = messaging.enqueue_whatsapp_inbound_message(
        message
    )

    assert queued["ok"] is True
    assert queued["queued"] is True
    assert message["message_id"] in (
        messaging._whatsapp_inbound_admitted
    )

    path = messaging._whatsapp_inbound_spool_path(
        message["message_id"]
    )
    assert path.exists()

    executor.futures[0].complete_result(
        {
            "ok": False,
            "message_id": message["message_id"],
            "sender": message["sender"],
            "stage": "conversation",
            "error": "conversation failed",
        }
    )

    assert message["message_id"] not in (
        messaging._whatsapp_inbound_admitted
    )

    # Failed processing must retain durable work.
    assert path.exists()


def test_worker_exception_releases_handoff_admission(
    isolated_worker,
):
    spool, executor = isolated_worker
    message = _message("wamid.worker-exception")

    queued = messaging.enqueue_whatsapp_inbound_message(
        message
    )

    assert queued["queued"] is True

    path = messaging._whatsapp_inbound_spool_path(
        message["message_id"]
    )
    assert path.exists()

    executor.futures[0].complete_exception(
        RuntimeError("worker crashed")
    )

    assert message["message_id"] not in (
        messaging._whatsapp_inbound_admitted
    )
    assert path.exists()


def test_failed_worker_allows_same_wamid_to_be_enqueued_again(
    isolated_worker,
):
    spool, executor = isolated_worker
    message = _message("wamid.retry-after-worker-failure")

    first = messaging.enqueue_whatsapp_inbound_message(
        message
    )

    assert first["queued"] is True
    assert len(executor.submissions) == 1

    executor.futures[0].complete_result(
        {
            "ok": False,
            "message_id": message["message_id"],
            "sender": message["sender"],
            "stage": "send",
        }
    )

    second = messaging.enqueue_whatsapp_inbound_message(
        message
    )

    assert second["ok"] is True
    assert second["queued"] is True
    assert second.get("duplicate") is not True
    assert len(executor.submissions) == 2


def test_failed_worker_releases_capacity_too(
    isolated_worker,
):
    _, executor = isolated_worker
    message = _message("wamid.capacity-release")

    before = messaging._whatsapp_inbound_pending

    queued = messaging.enqueue_whatsapp_inbound_message(
        message
    )

    assert queued["queued"] is True
    assert messaging._whatsapp_inbound_pending == before + 1

    executor.futures[0].complete_result(
        {
            "ok": False,
            "message_id": message["message_id"],
            "sender": message["sender"],
            "stage": "send",
        }
    )

    assert messaging._whatsapp_inbound_pending == before


def test_successful_worker_does_not_release_handoff_admission(
    isolated_worker,
):
    _, executor = isolated_worker
    message = _message("wamid.success")

    queued = messaging.enqueue_whatsapp_inbound_message(
        message
    )

    assert queued["queued"] is True

    executor.futures[0].complete_result(
        {
            "ok": True,
            "message_id": message["message_id"],
            "sender": message["sender"],
        }
    )

    # Success remains admitted so later Meta redelivery
    # is suppressed by handoff admission.
    assert message["message_id"] in (
        messaging._whatsapp_inbound_admitted
    )


def test_completion_callback_does_not_delete_durable_spool():
    source = inspect.getsource(
        messaging._whatsapp_inbound_future_done
    )

    # Durable deletion remains processor-owned.
    assert "_remove_whatsapp_inbound_message" not in source


def test_processor_remains_success_cleanup_authority():
    source = inspect.getsource(
        messaging.process_whatsapp_inbound_message
    )

    assert "_remove_whatsapp_inbound_message" in source
    assert "_finish_whatsapp_inbound" in source


def test_failed_worker_retry_contract_does_not_use_outbound_outbox():
    callback = inspect.getsource(
        messaging._whatsapp_inbound_future_done
    )
    enqueue = inspect.getsource(
        messaging.enqueue_whatsapp_inbound_message
    )

    assert "WA_OUTBOX" not in callback
    assert "WA_OUTBOX" not in enqueue
