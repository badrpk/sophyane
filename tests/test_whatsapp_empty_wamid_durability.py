from __future__ import annotations

import inspect

import pytest

import sophyane.cloud.messaging as messaging


class PendingFuture:
    def add_done_callback(self, callback):
        self.callback = callback

    def exception(self):
        return None


class RecordingExecutor:
    def __init__(self):
        self.messages = []
        self.futures = []

    def submit(self, fn, message):
        self.messages.append(dict(message))
        future = PendingFuture()
        self.futures.append(future)
        return future


@pytest.fixture
def isolated_inbound(monkeypatch, tmp_path):
    spool = tmp_path / "inbound"

    executor = RecordingExecutor()

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

    yield spool, executor

    messaging._reset_whatsapp_inbound_admission_for_tests()
    messaging._reset_whatsapp_inbound_capacity_for_tests()
    messaging._whatsapp_inbound_futures.clear()


def _empty_id_message(sender: str, text: str) -> dict[str, str]:
    return {
        "message_id": "",
        "sender": sender,
        "text": text,
    }


def test_real_parser_rejects_empty_message_id():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "",
                                    "from": "923001111111",
                                    "text": {
                                        "body": "empty"
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    assert (
        messaging.parse_whatsapp_inbound_messages(payload)
        == []
    )


def test_direct_enqueue_must_not_accept_empty_wamid(
    isolated_inbound,
):
    spool, executor = isolated_inbound

    result = messaging.enqueue_whatsapp_inbound_message(
        _empty_id_message(
            "923001111111",
            "first",
        )
    )

    assert result["ok"] is False
    assert result["queued"] is False
    assert result["stage"] == "handoff"

    assert executor.messages == []
    assert list(spool.glob("*.json")) == []


def test_two_empty_ids_cannot_alias_one_durable_job(
    isolated_inbound,
):
    spool, executor = isolated_inbound

    first = messaging.enqueue_whatsapp_inbound_message(
        _empty_id_message(
            "923001111111",
            "first",
        )
    )

    second = messaging.enqueue_whatsapp_inbound_message(
        _empty_id_message(
            "923002222222",
            "second",
        )
    )

    # Either reject both before persistence, or provide
    # genuinely distinct durable identities. The current
    # public seam has no alternate identity field, so the
    # minimal safe contract is rejection.
    assert first["ok"] is False
    assert second["ok"] is False

    assert executor.messages == []
    assert list(spool.glob("*.json")) == []


def test_empty_wamid_rejection_does_not_consume_capacity(
    isolated_inbound,
):
    _, _ = isolated_inbound

    before = messaging._whatsapp_inbound_pending

    result = messaging.enqueue_whatsapp_inbound_message(
        _empty_id_message(
            "923001111111",
            "capacity",
        )
    )

    after = messaging._whatsapp_inbound_pending

    assert result["ok"] is False
    assert after == before


def test_empty_wamid_rejection_does_not_claim_admission(
    isolated_inbound,
):
    _, _ = isolated_inbound

    result = messaging.enqueue_whatsapp_inbound_message(
        _empty_id_message(
            "923001111111",
            "admission",
        )
    )

    assert result["ok"] is False
    assert "" not in messaging._whatsapp_inbound_admitted


def test_empty_wamid_contract_does_not_use_outbound_outbox():
    source = inspect.getsource(
        messaging.enqueue_whatsapp_inbound_message
    )

    assert "WA_OUTBOX" not in source
