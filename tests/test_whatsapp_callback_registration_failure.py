from __future__ import annotations

import json

import pytest

import sophyane.cloud.messaging as messaging


class RegistrationFailingFuture:
    def __init__(self):
        self.callback_attempts = 0

    def add_done_callback(self, callback):
        self.callback_attempts += 1
        raise RuntimeError(
            "callback registration failed"
        )

    def result(self):
        return {
            "ok": False,
            "stage": "conversation",
        }

    def exception(self):
        return None


class RegistrationFailingExecutor:
    def __init__(self):
        self.submissions = []
        self.futures = []

    def submit(self, fn, message):
        future = RegistrationFailingFuture()

        self.submissions.append(
            (fn, dict(message))
        )
        self.futures.append(future)

        return future


@pytest.fixture
def isolated_runtime(monkeypatch, tmp_path):
    spool = tmp_path / "inbound"
    executor = RegistrationFailingExecutor()

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


def _message(
    message_id="wamid.callback-registration",
):
    return {
        "message_id": message_id,
        "sender": "923001234567",
        "text": "hello",
    }


def _write_durable_message(spool, message):
    spool.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = messaging._whatsapp_inbound_spool_path(
        message["message_id"]
    )

    path.write_text(
        json.dumps(
            {
                "message": dict(message),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    return path


def test_enqueue_registration_failure_does_not_leak_capacity(
    isolated_runtime,
):
    _, executor = isolated_runtime
    message = _message(
        "wamid.enqueue-registration-capacity"
    )

    before = messaging._whatsapp_inbound_pending

    result = messaging.enqueue_whatsapp_inbound_message(
        message
    )

    assert result["ok"] is True
    assert result["queued"] is True
    assert len(executor.submissions) == 1
    assert executor.futures[0].callback_attempts == 1

    assert messaging._whatsapp_inbound_pending == before


def test_enqueue_registration_failure_does_not_leak_future(
    isolated_runtime,
):
    _, executor = isolated_runtime
    message = _message(
        "wamid.enqueue-registration-future"
    )

    result = messaging.enqueue_whatsapp_inbound_message(
        message
    )

    assert result["queued"] is True

    future = executor.futures[0]

    assert future not in (
        messaging._whatsapp_inbound_futures
    )


def test_enqueue_registration_failure_releases_admission(
    isolated_runtime,
):
    _, executor = isolated_runtime
    message = _message(
        "wamid.enqueue-registration-admission"
    )

    result = messaging.enqueue_whatsapp_inbound_message(
        message
    )

    assert result["queued"] is True
    assert executor.futures[0].callback_attempts == 1

    assert message["message_id"] not in (
        messaging._whatsapp_inbound_admitted
    )


def test_enqueue_registration_failure_retains_durable_job(
    isolated_runtime,
):
    _, executor = isolated_runtime
    message = _message(
        "wamid.enqueue-registration-durable"
    )

    result = messaging.enqueue_whatsapp_inbound_message(
        message
    )

    assert result["queued"] is True

    path = messaging._whatsapp_inbound_spool_path(
        message["message_id"]
    )

    assert path.exists()


def test_enqueue_registration_failure_allows_retry(
    isolated_runtime,
):
    _, executor = isolated_runtime
    message = _message(
        "wamid.enqueue-registration-retry"
    )

    first = messaging.enqueue_whatsapp_inbound_message(
        message
    )

    assert first["queued"] is True
    assert len(executor.submissions) == 1

    second = messaging.enqueue_whatsapp_inbound_message(
        message
    )

    assert second["ok"] is True
    assert second["queued"] is True
    assert second.get("duplicate") is not True
    assert len(executor.submissions) == 2


def test_replay_registration_failure_does_not_leak_capacity(
    isolated_runtime,
):
    spool, executor = isolated_runtime
    message = _message(
        "wamid.replay-registration-capacity"
    )

    path = _write_durable_message(
        spool,
        message,
    )
    assert path.exists()

    before = messaging._whatsapp_inbound_pending

    results = messaging._replay_whatsapp_inbound_spool()

    assert len(results) == 1
    assert results[0]["queued"] is True
    assert len(executor.submissions) == 1
    assert executor.futures[0].callback_attempts == 1

    assert messaging._whatsapp_inbound_pending == before


def test_replay_registration_failure_does_not_leak_future(
    isolated_runtime,
):
    spool, executor = isolated_runtime
    message = _message(
        "wamid.replay-registration-future"
    )

    _write_durable_message(
        spool,
        message,
    )

    results = messaging._replay_whatsapp_inbound_spool()

    assert results[0]["queued"] is True

    future = executor.futures[0]

    assert future not in (
        messaging._whatsapp_inbound_futures
    )


def test_replay_registration_failure_releases_admission(
    isolated_runtime,
):
    spool, executor = isolated_runtime
    message = _message(
        "wamid.replay-registration-admission"
    )

    path = _write_durable_message(
        spool,
        message,
    )

    results = messaging._replay_whatsapp_inbound_spool()

    assert results[0]["queued"] is True
    assert executor.futures[0].callback_attempts == 1

    assert message["message_id"] not in (
        messaging._whatsapp_inbound_admitted
    )

    # Registration failure must never delete durable work.
    assert path.exists()


def test_registration_failure_contract_does_not_use_outbound_outbox():
    import inspect

    enqueue = inspect.getsource(
        messaging.enqueue_whatsapp_inbound_message
    )
    replay = inspect.getsource(
        messaging._replay_whatsapp_inbound_spool
    )

    assert "WA_OUTBOX" not in enqueue
    assert "WA_OUTBOX" not in replay
