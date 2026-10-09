from __future__ import annotations

import threading

import pytest

import sophyane.cloud.messaging as messaging


@pytest.fixture(autouse=True)
def _isolated_whatsapp_inbound_spool(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        messaging,
        "WHATSAPP_INBOUND_SPOOL",
        tmp_path / "whatsapp_inbound",
    )


def _message(
    message_id: str = "wamid.worker",
) -> dict[str, str]:
    return {
        "message_id": message_id,
        "sender": "923001234567",
        "text": "worker lifecycle",
    }


def test_whatsapp_inbound_uses_shared_bounded_executor():
    executor = getattr(
        messaging,
        "_whatsapp_inbound_executor",
        None,
    )

    assert executor is not None

    max_workers = getattr(
        executor,
        "_max_workers",
        None,
    )

    assert isinstance(max_workers, int)
    assert max_workers >= 1
    assert max_workers <= 8


def test_enqueue_submits_to_shared_executor_not_new_thread(
    monkeypatch,
):
    submitted: list[tuple] = []

    class FakeFuture:
        def add_done_callback(self, callback):
            return None

    class FakeExecutor:
        def submit(self, function, *args, **kwargs):
            submitted.append(
                (function, args, kwargs)
            )
            return FakeFuture()

    fake_executor = FakeExecutor()

    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_executor",
        fake_executor,
    )

    def forbidden_thread(*args, **kwargs):
        raise AssertionError(
            "enqueue must not create one Thread per message"
        )

    monkeypatch.setattr(
        threading,
        "Thread",
        forbidden_thread,
    )

    result = messaging.enqueue_whatsapp_inbound_message(
        _message()
    )

    assert result["ok"] is True
    assert result["queued"] is True
    assert result["message_id"] == "wamid.worker"

    assert len(submitted) == 1

    function, args, kwargs = submitted[0]

    assert callable(function)
    assert len(args) == 1
    assert args[0] == _message()
    assert kwargs == {}


def test_submission_failure_is_structured(
    monkeypatch,
):
    class RejectingExecutor:
        def submit(self, *args, **kwargs):
            raise RuntimeError(
                "worker pool unavailable"
            )

    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_executor",
        RejectingExecutor(),
        raising=False,
    )

    result = messaging.enqueue_whatsapp_inbound_message(
        _message("wamid.reject")
    )

    assert result["ok"] is False
    assert result["queued"] is False
    assert result["message_id"] == "wamid.reject"
    assert result["sender"] == "923001234567"
    assert result["stage"] == "handoff"
    assert "worker pool unavailable" in result["error"]


def test_worker_exception_is_contained_after_submission(
    monkeypatch,
):
    callbacks: list = []

    class FailedFuture:
        def add_done_callback(self, callback):
            callbacks.append(callback)

        def exception(self):
            return RuntimeError(
                "background processor exploded"
            )

    class FakeExecutor:
        def submit(self, function, *args, **kwargs):
            return FailedFuture()

    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_executor",
        FakeExecutor(),
        raising=False,
    )

    result = messaging.enqueue_whatsapp_inbound_message(
        _message("wamid.background-failure")
    )

    assert result["ok"] is True
    assert result["queued"] is True

    # Completion/failure observation must itself be safe.
    for callback in callbacks:
        callback(FailedFuture())


def test_worker_reset_seam_exists():
    reset = getattr(
        messaging,
        "_reset_whatsapp_inbound_worker_for_tests",
        None,
    )

    assert callable(reset)


def test_worker_reset_replaces_executor():
    reset = getattr(
        messaging,
        "_reset_whatsapp_inbound_worker_for_tests",
        None,
    )

    assert callable(reset)

    before = getattr(
        messaging,
        "_whatsapp_inbound_executor",
        None,
    )

    assert before is not None

    reset()

    after = getattr(
        messaging,
        "_whatsapp_inbound_executor",
        None,
    )

    assert after is not None
    assert after is not before


def test_worker_drain_seam_exists():
    drain = getattr(
        messaging,
        "_drain_whatsapp_inbound_worker_for_tests",
        None,
    )

    assert callable(drain)


def test_worker_drain_waits_for_submitted_work(
    monkeypatch,
):
    drain = getattr(
        messaging,
        "_drain_whatsapp_inbound_worker_for_tests",
        None,
    )

    assert callable(drain)

    completed = threading.Event()

    def fake_processor(message):
        completed.set()
        return {
            "ok": True,
            "message_id": message["message_id"],
        }

    monkeypatch.setattr(
        messaging,
        "process_whatsapp_inbound_message",
        fake_processor,
    )

    result = messaging.enqueue_whatsapp_inbound_message(
        _message("wamid.drain")
    )

    assert result["ok"] is True
    assert result["queued"] is True

    drain()

    assert completed.is_set()


def test_handoff_does_not_move_idempotency_authority():
    import inspect

    enqueue_source = inspect.getsource(
        messaging.enqueue_whatsapp_inbound_message
    )

    processor_source = inspect.getsource(
        messaging.process_whatsapp_inbound_message
    )

    assert "_begin_whatsapp_inbound(" not in enqueue_source
    assert "_finish_whatsapp_inbound(" not in enqueue_source

    assert "_begin_whatsapp_inbound(" in processor_source
    assert "_finish_whatsapp_inbound(" in processor_source
