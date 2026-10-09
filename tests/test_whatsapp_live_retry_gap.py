from __future__ import annotations

import json
import inspect

import pytest

import sophyane.cloud.messaging as messaging


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch, tmp_path):
    messaging._reset_whatsapp_inbound_worker_for_tests()
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
    messaging._reset_whatsapp_inbound_admission_for_tests()
    messaging._reset_whatsapp_inbound_idempotency_for_tests()


def _message(message_id: str) -> dict[str, str]:
    return {
        "message_id": message_id,
        "sender": "923001234567",
        "text": "retry me",
    }


def _fail_processor(message):
    return {
        "ok": False,
        "message_id": message["message_id"],
        "sender": message["sender"],
        "stage": "send",
        "error": "synthetic failure",
    }


def test_failed_background_job_remains_durable(
    monkeypatch,
):
    monkeypatch.setattr(
        messaging,
        "process_whatsapp_inbound_message",
        _fail_processor,
    )

    message = _message(
        "wamid.live-retry-durable"
    )

    result = messaging.enqueue_whatsapp_inbound_message(
        message
    )

    assert result["ok"] is True
    assert result["queued"] is True

    messaging._drain_whatsapp_inbound_worker_for_tests()

    path = messaging._whatsapp_inbound_spool_path(
        message["message_id"]
    )

    assert path.exists()


def test_failed_background_job_releases_admission(
    monkeypatch,
):
    monkeypatch.setattr(
        messaging,
        "process_whatsapp_inbound_message",
        _fail_processor,
    )

    message = _message(
        "wamid.live-retry-admission"
    )

    result = messaging.enqueue_whatsapp_inbound_message(
        message
    )

    assert result["ok"] is True

    messaging._drain_whatsapp_inbound_worker_for_tests()

    with messaging._whatsapp_inbound_admission_lock():
        assert (
            message["message_id"]
            not in messaging._whatsapp_inbound_admitted
        )


def test_failed_background_job_releases_capacity(
    monkeypatch,
):
    monkeypatch.setattr(
        messaging,
        "process_whatsapp_inbound_message",
        _fail_processor,
    )

    result = messaging.enqueue_whatsapp_inbound_message(
        _message("wamid.live-retry-capacity")
    )

    assert result["ok"] is True

    messaging._drain_whatsapp_inbound_worker_for_tests()

    assert messaging._whatsapp_inbound_pending == 0


def test_live_process_exposes_retry_trigger():
    assert hasattr(
        messaging,
        "_retry_whatsapp_inbound_spool",
    )


def test_retry_trigger_resubmits_failed_durable_job(
    monkeypatch,
):
    attempts = []

    def processor(message):
        attempts.append(
            message["message_id"]
        )

        if len(attempts) == 1:
            return {
                "ok": False,
                "message_id": message["message_id"],
                "sender": message["sender"],
                "stage": "send",
                "error": "first attempt fails",
            }

        messaging._remove_whatsapp_inbound_message(
            message["message_id"]
        )

        return {
            "ok": True,
            "message_id": message["message_id"],
            "sender": message["sender"],
        }

    monkeypatch.setattr(
        messaging,
        "process_whatsapp_inbound_message",
        processor,
    )

    message = _message(
        "wamid.live-retry-resubmit"
    )

    result = messaging.enqueue_whatsapp_inbound_message(
        message
    )

    assert result["ok"] is True
    assert result["queued"] is True

    messaging._drain_whatsapp_inbound_worker_for_tests()

    assert attempts == [
        message["message_id"]
    ]

    retry = getattr(
        messaging,
        "_retry_whatsapp_inbound_spool",
        None,
    )

    assert callable(retry)

    # A retry trigger scans the durable spool; it does not override durable
    # retry eligibility. Make this job eligible without sleeping so this
    # contract continues to test resubmission rather than backoff timing.
    durable_path = messaging._whatsapp_inbound_spool_path(
        message["message_id"]
    )

    durable_payload = json.loads(
        durable_path.read_text(
            encoding="utf-8"
        )
    )

    durable_payload["next_attempt_at"] = 0.0

    durable_path.write_text(
        json.dumps(
            durable_payload,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    retry()

    messaging._drain_whatsapp_inbound_worker_for_tests()

    assert attempts == [
        message["message_id"],
        message["message_id"],
    ]

    assert not (
        messaging._whatsapp_inbound_spool_path(
            message["message_id"]
        ).exists()
    )


def test_retry_trigger_reuses_durable_replay_authority():
    retry = getattr(
        messaging,
        "_retry_whatsapp_inbound_spool",
        None,
    )

    assert callable(retry)

    source = inspect.getsource(retry)

    assert (
        "_replay_whatsapp_inbound_spool"
        in source
    )


def test_live_retry_contract_does_not_use_outbound_outbox():
    source = inspect.getsource(
        messaging._replay_whatsapp_inbound_spool
    )

    assert "WA_OUTBOX" not in source
