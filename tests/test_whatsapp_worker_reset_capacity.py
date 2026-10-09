from __future__ import annotations

import inspect

import pytest

import sophyane.cloud.messaging as messaging


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch, tmp_path):
    messaging._reset_whatsapp_inbound_worker_for_tests()
    messaging._reset_whatsapp_inbound_capacity_for_tests()
    messaging._reset_whatsapp_inbound_admission_for_tests()
    messaging._reset_whatsapp_inbound_idempotency_for_tests()

    monkeypatch.setattr(
        messaging,
        "WHATSAPP_INBOUND_SPOOL",
        tmp_path / "whatsapp_inbound",
    )

    yield

    messaging._drain_whatsapp_inbound_worker_for_tests()
    messaging._reset_whatsapp_inbound_worker_for_tests()
    messaging._reset_whatsapp_inbound_capacity_for_tests()
    messaging._reset_whatsapp_inbound_admission_for_tests()
    messaging._reset_whatsapp_inbound_idempotency_for_tests()


def _message(message_id: str) -> dict[str, str]:
    return {
        "message_id": message_id,
        "sender": "923001234567",
        "text": "hello",
    }


def test_worker_reset_restores_zero_pending_capacity():
    messaging._whatsapp_inbound_pending = (
        messaging._WHATSAPP_INBOUND_PENDING_LIMIT
    )

    messaging._reset_whatsapp_inbound_worker_for_tests()

    assert messaging._whatsapp_inbound_pending == 0


def test_fresh_worker_accepts_job_after_stale_capacity_reset(
    monkeypatch,
):
    messaging._whatsapp_inbound_pending = (
        messaging._WHATSAPP_INBOUND_PENDING_LIMIT
    )

    messaging._reset_whatsapp_inbound_worker_for_tests()

    monkeypatch.setattr(
        messaging,
        "process_whatsapp_inbound_message",
        lambda message: {
            "ok": True,
            "message_id": message["message_id"],
            "sender": message["sender"],
        },
    )

    result = messaging.enqueue_whatsapp_inbound_message(
        _message("wamid.reset-capacity")
    )

    assert result["ok"] is True
    assert result["queued"] is True
    assert result.get("stage") != "backpressure"

    messaging._drain_whatsapp_inbound_worker_for_tests()


def test_reset_capacity_does_not_underflow_after_completion(
    monkeypatch,
):
    messaging._whatsapp_inbound_pending = (
        messaging._WHATSAPP_INBOUND_PENDING_LIMIT
    )

    messaging._reset_whatsapp_inbound_worker_for_tests()

    monkeypatch.setattr(
        messaging,
        "process_whatsapp_inbound_message",
        lambda message: {
            "ok": True,
            "message_id": message["message_id"],
            "sender": message["sender"],
        },
    )

    result = messaging.enqueue_whatsapp_inbound_message(
        _message("wamid.reset-completion")
    )

    assert result["ok"] is True
    assert result["queued"] is True

    messaging._drain_whatsapp_inbound_worker_for_tests()

    assert messaging._whatsapp_inbound_pending == 0


def test_worker_reset_keeps_future_tracking_clean():
    messaging._reset_whatsapp_inbound_worker_for_tests()

    assert (
        messaging._snapshot_whatsapp_inbound_futures()
        == ()
    )


def test_worker_reset_uses_existing_capacity_reset_authority():
    source = inspect.getsource(
        messaging._reset_whatsapp_inbound_worker_for_tests
    )

    assert (
        "_reset_whatsapp_inbound_capacity_for_tests()"
        in source
    )


def test_worker_reset_capacity_contract_does_not_use_outbound_outbox():
    source = inspect.getsource(
        messaging._reset_whatsapp_inbound_worker_for_tests
    )

    assert "WA_OUTBOX" not in source
