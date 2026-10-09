from __future__ import annotations

import sophyane.cloud.messaging as messaging


def _message(
    message_id: str = "wamid.idempotency-proof",
) -> dict[str, str]:
    return {
        "message_id": message_id,
        "sender": "923001234567",
        "text": "hello once",
    }


def _reset_idempotency_state() -> None:
    reset = getattr(
        messaging,
        "_reset_whatsapp_inbound_idempotency_for_tests",
        None,
    )
    if reset is not None:
        reset()


def test_successful_wamid_is_dispatched_only_once(
    monkeypatch,
):
    _reset_idempotency_state()

    conversation_calls: list[str] = []
    send_calls: list[tuple[str, str]] = []

    def fake_reply(text: str) -> str:
        conversation_calls.append(text)
        return "reply once"

    def fake_send(to: str, text: str) -> dict:
        send_calls.append((to, text))
        return {
            "ok": True,
            "channel": "whatsapp",
            "to": to,
        }

    monkeypatch.setattr(
        messaging,
        "_whatsapp_conversation_reply",
        fake_reply,
    )
    monkeypatch.setattr(
        messaging,
        "send_whatsapp",
        fake_send,
    )

    first = messaging.process_whatsapp_inbound_message(
        _message()
    )
    second = messaging.process_whatsapp_inbound_message(
        _message()
    )

    assert first["ok"] is True
    assert first["message_id"] == "wamid.idempotency-proof"

    assert second["ok"] is True
    assert second["message_id"] == "wamid.idempotency-proof"
    assert second["duplicate"] is True

    assert conversation_calls == ["hello once"]
    assert send_calls == [
        ("923001234567", "reply once"),
    ]


def test_different_wamids_are_processed_independently(
    monkeypatch,
):
    _reset_idempotency_state()

    conversation_calls: list[str] = []
    send_calls: list[tuple[str, str]] = []

    def fake_reply(text: str) -> str:
        conversation_calls.append(text)
        return f"reply:{text}"

    def fake_send(to: str, text: str) -> dict:
        send_calls.append((to, text))
        return {
            "ok": True,
            "channel": "whatsapp",
            "to": to,
        }

    monkeypatch.setattr(
        messaging,
        "_whatsapp_conversation_reply",
        fake_reply,
    )
    monkeypatch.setattr(
        messaging,
        "send_whatsapp",
        fake_send,
    )

    first = messaging.process_whatsapp_inbound_message(
        {
            "message_id": "wamid.one",
            "sender": "923001111111",
            "text": "one",
        }
    )
    second = messaging.process_whatsapp_inbound_message(
        {
            "message_id": "wamid.two",
            "sender": "923002222222",
            "text": "two",
        }
    )

    assert first["ok"] is True
    assert second["ok"] is True

    assert conversation_calls == ["one", "two"]
    assert send_calls == [
        ("923001111111", "reply:one"),
        ("923002222222", "reply:two"),
    ]


def test_conversation_failure_does_not_consume_wamid(
    monkeypatch,
):
    _reset_idempotency_state()

    attempts = 0
    send_calls: list[tuple[str, str]] = []

    def flaky_reply(_text: str) -> str:
        nonlocal attempts
        attempts += 1

        if attempts == 1:
            raise RuntimeError("temporary conversation failure")

        return "recovered reply"

    def fake_send(to: str, text: str) -> dict:
        send_calls.append((to, text))
        return {
            "ok": True,
            "channel": "whatsapp",
            "to": to,
        }

    monkeypatch.setattr(
        messaging,
        "_whatsapp_conversation_reply",
        flaky_reply,
    )
    monkeypatch.setattr(
        messaging,
        "send_whatsapp",
        fake_send,
    )

    first = messaging.process_whatsapp_inbound_message(
        _message("wamid.retry-conversation")
    )
    second = messaging.process_whatsapp_inbound_message(
        _message("wamid.retry-conversation")
    )

    assert first["ok"] is False
    assert first["stage"] == "conversation"

    assert second["ok"] is True
    assert second.get("duplicate") is not True

    assert attempts == 2
    assert send_calls == [
        ("923001234567", "recovered reply"),
    ]


def test_send_failure_does_not_consume_wamid(
    monkeypatch,
):
    _reset_idempotency_state()

    conversation_calls: list[str] = []
    send_attempts = 0

    def fake_reply(text: str) -> str:
        conversation_calls.append(text)
        return "generated reply"

    def flaky_send(to: str, text: str) -> dict:
        nonlocal send_attempts
        send_attempts += 1

        if send_attempts == 1:
            return {
                "ok": False,
                "channel": "whatsapp",
                "to": to,
                "error": "temporary delivery failure",
            }

        return {
            "ok": True,
            "channel": "whatsapp",
            "to": to,
        }

    monkeypatch.setattr(
        messaging,
        "_whatsapp_conversation_reply",
        fake_reply,
    )
    monkeypatch.setattr(
        messaging,
        "send_whatsapp",
        flaky_send,
    )

    first = messaging.process_whatsapp_inbound_message(
        _message("wamid.retry-send")
    )
    second = messaging.process_whatsapp_inbound_message(
        _message("wamid.retry-send")
    )

    assert first["ok"] is False
    assert first["stage"] == "send"

    assert second["ok"] is True
    assert second.get("duplicate") is not True

    assert send_attempts == 2

    # Retrying the complete dispatch is acceptable at this boundary.
    assert conversation_calls == [
        "hello once",
        "hello once",
    ]


def test_send_exception_does_not_consume_wamid(
    monkeypatch,
):
    _reset_idempotency_state()

    send_attempts = 0

    monkeypatch.setattr(
        messaging,
        "_whatsapp_conversation_reply",
        lambda _text: "generated reply",
    )

    def flaky_send(to: str, text: str) -> dict:
        nonlocal send_attempts
        send_attempts += 1

        if send_attempts == 1:
            raise RuntimeError("temporary send exception")

        return {
            "ok": True,
            "channel": "whatsapp",
            "to": to,
        }

    monkeypatch.setattr(
        messaging,
        "send_whatsapp",
        flaky_send,
    )

    first = messaging.process_whatsapp_inbound_message(
        _message("wamid.retry-send-exception")
    )
    second = messaging.process_whatsapp_inbound_message(
        _message("wamid.retry-send-exception")
    )

    assert first["ok"] is False
    assert first["stage"] == "send"

    assert second["ok"] is True
    assert second.get("duplicate") is not True

    assert send_attempts == 2


def test_success_then_third_delivery_remains_duplicate(
    monkeypatch,
):
    _reset_idempotency_state()

    sends = 0

    monkeypatch.setattr(
        messaging,
        "_whatsapp_conversation_reply",
        lambda _text: "stable reply",
    )

    def fake_send(to: str, text: str) -> dict:
        nonlocal sends
        sends += 1
        return {
            "ok": True,
            "channel": "whatsapp",
            "to": to,
        }

    monkeypatch.setattr(
        messaging,
        "send_whatsapp",
        fake_send,
    )

    first = messaging.process_whatsapp_inbound_message(
        _message("wamid.stable")
    )
    second = messaging.process_whatsapp_inbound_message(
        _message("wamid.stable")
    )
    third = messaging.process_whatsapp_inbound_message(
        _message("wamid.stable")
    )

    assert first["ok"] is True

    assert second["ok"] is True
    assert second["duplicate"] is True

    assert third["ok"] is True
    assert third["duplicate"] is True

    assert sends == 1
