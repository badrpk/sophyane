from __future__ import annotations

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
    message_id: str,
) -> dict[str, str]:
    return {
        "message_id": message_id,
        "sender": "923001234567",
        "text": "duplicate admission",
    }


class _Future:
    def add_done_callback(self, callback):
        self.callback = callback

    def exception(self):
        return None


class _HoldingExecutor:
    def __init__(self):
        self.submissions: list[
            tuple[object, tuple, dict]
        ] = []

    def submit(self, function, *args, **kwargs):
        self.submissions.append(
            (function, args, kwargs)
        )
        return _Future()


def _reset_admission_if_present():
    reset = getattr(
        messaging,
        "_reset_whatsapp_inbound_admission_for_tests",
        None,
    )

    if callable(reset):
        reset()


def test_duplicate_handoff_is_admitted_only_once(
    monkeypatch,
):
    _reset_admission_if_present()

    executor = _HoldingExecutor()

    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_executor",
        executor,
    )

    message = _message("wamid.same")

    first = messaging.enqueue_whatsapp_inbound_message(
        message
    )

    second = messaging.enqueue_whatsapp_inbound_message(
        message
    )

    assert first["ok"] is True
    assert first["queued"] is True
    assert first.get("duplicate") is not True

    assert second["ok"] is True
    assert second["queued"] is False
    assert second["duplicate"] is True

    assert second["message_id"] == "wamid.same"
    assert second["sender"] == "923001234567"

    assert len(executor.submissions) == 1


def test_different_wamids_are_independently_admitted(
    monkeypatch,
):
    _reset_admission_if_present()

    executor = _HoldingExecutor()

    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_executor",
        executor,
    )

    first = messaging.enqueue_whatsapp_inbound_message(
        _message("wamid.one")
    )

    second = messaging.enqueue_whatsapp_inbound_message(
        _message("wamid.two")
    )

    assert first["ok"] is True
    assert first["queued"] is True

    assert second["ok"] is True
    assert second["queued"] is True

    assert len(executor.submissions) == 2


def test_submission_failure_releases_admission(
    monkeypatch,
):
    _reset_admission_if_present()

    class RejectOnceExecutor:
        def __init__(self):
            self.calls = 0

        def submit(self, function, *args, **kwargs):
            self.calls += 1

            if self.calls == 1:
                raise RuntimeError(
                    "temporary submission failure"
                )

            return _Future()

    executor = RejectOnceExecutor()

    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_executor",
        executor,
    )

    message = _message("wamid.retry")

    failed = messaging.enqueue_whatsapp_inbound_message(
        message
    )

    retried = messaging.enqueue_whatsapp_inbound_message(
        message
    )

    assert failed["ok"] is False
    assert failed["queued"] is False
    assert failed["stage"] == "handoff"

    assert retried["ok"] is True
    assert retried["queued"] is True
    assert retried.get("duplicate") is not True

    assert executor.calls == 2


def test_admission_reset_seam_exists():
    reset = getattr(
        messaging,
        "_reset_whatsapp_inbound_admission_for_tests",
        None,
    )

    assert callable(reset)


def test_admission_reset_allows_same_wamid_again(
    monkeypatch,
):
    reset = getattr(
        messaging,
        "_reset_whatsapp_inbound_admission_for_tests",
        None,
    )

    assert callable(reset)

    reset()

    executor = _HoldingExecutor()

    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_executor",
        executor,
    )

    message = _message("wamid.reset")

    first = messaging.enqueue_whatsapp_inbound_message(
        message
    )

    duplicate = messaging.enqueue_whatsapp_inbound_message(
        message
    )

    assert first["queued"] is True
    assert duplicate["duplicate"] is True
    assert len(executor.submissions) == 1

    reset()

    again = messaging.enqueue_whatsapp_inbound_message(
        message
    )

    assert again["ok"] is True
    assert again["queued"] is True
    assert again.get("duplicate") is not True

    assert len(executor.submissions) == 2


def test_empty_message_id_is_rejected_before_admission(
    monkeypatch,
):
    _reset_admission_if_present()

    executor = _HoldingExecutor()

    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_executor",
        executor,
    )

    message = _message("")

    first = messaging.enqueue_whatsapp_inbound_message(
        message
    )

    second = messaging.enqueue_whatsapp_inbound_message(
        message
    )

    assert first["ok"] is False
    assert first["queued"] is False
    assert first["stage"] == "handoff"

    assert second["ok"] is False
    assert second["queued"] is False
    assert second["stage"] == "handoff"

    assert "" not in messaging._whatsapp_inbound_admitted
    assert executor.submissions == []



def test_admission_does_not_steal_processor_idempotency():
    import inspect

    enqueue_source = inspect.getsource(
        messaging.enqueue_whatsapp_inbound_message
    )

    processor_source = inspect.getsource(
        messaging.process_whatsapp_inbound_message
    )

    # Admission must use a separate boundary. Do not simply move
    # execution idempotency into enqueue(), because the worker would
    # then encounter its own claim as a duplicate.
    assert "_begin_whatsapp_inbound(" not in enqueue_source
    assert "_finish_whatsapp_inbound(" not in enqueue_source

    assert "_begin_whatsapp_inbound(" in processor_source
    assert "_finish_whatsapp_inbound(" in processor_source
