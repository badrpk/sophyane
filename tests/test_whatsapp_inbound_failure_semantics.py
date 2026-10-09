from __future__ import annotations

import io
import json

import sophyane.cloud.messaging as messaging
import sophyane.cloud.portal as portal


def _message(
    *,
    message_id: str = "wamid.failure-proof",
    sender: str = "923001234567",
    text: str = "hello failure boundary",
) -> dict[str, str]:
    return {
        "message_id": message_id,
        "sender": sender,
        "text": text,
    }


class _Handler:
    path = "/api/v1/messaging/whatsapp/webhook"

    def __init__(self) -> None:
        raw = json.dumps(
            {
                "object": "whatsapp_business_account",
                "entry": [
                    {
                        "changes": [
                            {
                                "field": "messages",
                                "value": {
                                    "statuses": [],
                                },
                            }
                        ],
                    }
                ],
            },
            separators=(",", ":"),
        ).encode("utf-8")

        self.headers = {
            "Content-Length": str(len(raw)),
            "Content-Type": "application/json",
        }
        self.rfile = io.BytesIO(raw)
        self.wfile = io.BytesIO()
        self.status = None
        self.response_headers: dict[str, str] = {}

    def send_response(self, status: int) -> None:
        self.status = status

    def send_header(self, name: str, value: str) -> None:
        self.response_headers[name] = value

    def end_headers(self) -> None:
        pass


def test_conversation_failure_becomes_structured_dispatch_failure(
    monkeypatch,
):
    send_calls: list[tuple[str, str]] = []

    def failing_conversation(_text: str) -> str:
        raise RuntimeError("conversation exploded")

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
        failing_conversation,
    )
    monkeypatch.setattr(
        messaging,
        "send_whatsapp",
        fake_send,
    )

    result = messaging.process_whatsapp_inbound_message(
        _message()
    )

    assert result["ok"] is False
    assert result["message_id"] == "wamid.failure-proof"
    assert result["sender"] == "923001234567"
    assert result["stage"] == "conversation"
    assert "conversation exploded" in result["error"]

    # Never send a fabricated/empty reply after generation failed.
    assert send_calls == []


def test_outbound_failure_is_returned_without_losing_reply(
    monkeypatch,
):
    monkeypatch.setattr(
        messaging,
        "_whatsapp_conversation_reply",
        lambda _text: "generated reply",
    )

    monkeypatch.setattr(
        messaging,
        "send_whatsapp",
        lambda to, text: {
            "ok": False,
            "channel": "whatsapp",
            "to": to,
            "error": "delivery unavailable",
        },
    )

    result = messaging.process_whatsapp_inbound_message(
        _message(
            message_id="wamid.send-failure",
            text="generate but fail delivery",
        )
    )

    assert result["ok"] is False
    assert result["message_id"] == "wamid.send-failure"
    assert result["sender"] == "923001234567"
    assert result["reply"] == "generated reply"
    assert result["stage"] == "send"
    assert result["send"]["ok"] is False
    assert result["send"]["error"] == "delivery unavailable"


def test_send_exception_becomes_structured_dispatch_failure(
    monkeypatch,
):
    monkeypatch.setattr(
        messaging,
        "_whatsapp_conversation_reply",
        lambda _text: "generated reply",
    )

    def exploding_send(_to: str, _text: str) -> dict:
        raise RuntimeError("send exploded")

    monkeypatch.setattr(
        messaging,
        "send_whatsapp",
        exploding_send,
    )

    result = messaging.process_whatsapp_inbound_message(
        _message(message_id="wamid.send-exception")
    )

    assert result["ok"] is False
    assert result["message_id"] == "wamid.send-exception"
    assert result["sender"] == "923001234567"
    assert result["reply"] == "generated reply"
    assert result["stage"] == "send"
    assert "send exploded" in result["error"]


def test_webhook_ack_survives_one_dispatch_failure(
    monkeypatch,
):
    messages = [
        _message(
            message_id="wamid.good",
            sender="923001111111",
            text="good",
        ),
        _message(
            message_id="wamid.bad",
            sender="923002222222",
            text="bad",
        ),
    ]

    monkeypatch.setattr(
        messaging,
        "parse_whatsapp_inbound_messages",
        lambda _payload: messages,
    )

    handoffs: list[dict[str, str]] = []

    def fake_enqueue(
        message: dict[str, str],
    ) -> dict:
        handoffs.append(message)

        return {
            "ok": True,
            "queued": True,
            "message_id": message["message_id"],
            "sender": message["sender"],
        }

    monkeypatch.setattr(
        messaging,
        "enqueue_whatsapp_inbound_message",
        fake_enqueue,
    )

    def forbidden_inline_processor(
        message: dict[str, str],
    ) -> dict:
        raise AssertionError(
            "webhook must not observe background "
            "processor failure inline"
        )

    monkeypatch.setattr(
        messaging,
        "process_whatsapp_inbound_message",
        forbidden_inline_processor,
    )

    handler = _Handler()
    app = portal.create_portal_app()

    handled = app.handle_api(
        "POST",
        "/api/v1/messaging/whatsapp/webhook",
        handler,
    )

    assert handled is True
    assert handler.status == 200
    assert handoffs == messages

    response = json.loads(
        handler.wfile.getvalue().decode("utf-8")
    )

    assert response["ok"] is True
    assert response["messages"] == messages
    assert len(response["dispatch"]) == 2

    assert all(
        item["ok"] is True
        for item in response["dispatch"]
    )

    assert all(
        item["queued"] is True
        for item in response["dispatch"]
    )

    assert [
        item["message_id"]
        for item in response["dispatch"]
    ] == [
        "wamid.good",
        "wamid.bad",
    ]


def test_webhook_ack_survives_all_dispatch_failures(
    monkeypatch,
):
    messages = [
        _message(
            message_id="wamid.fail-one",
            sender="923003333333",
            text="one",
        ),
        _message(
            message_id="wamid.fail-two",
            sender="923004444444",
            text="two",
        ),
    ]

    monkeypatch.setattr(
        messaging,
        "parse_whatsapp_inbound_messages",
        lambda _payload: messages,
    )

    handoffs: list[dict[str, str]] = []

    def fake_enqueue(
        message: dict[str, str],
    ) -> dict:
        handoffs.append(message)

        return {
            "ok": True,
            "queued": True,
            "message_id": message["message_id"],
            "sender": message["sender"],
        }

    monkeypatch.setattr(
        messaging,
        "enqueue_whatsapp_inbound_message",
        fake_enqueue,
    )

    def forbidden_inline_processor(
        message: dict[str, str],
    ) -> dict:
        raise AssertionError(
            "background failure must not cross "
            "the webhook ACK boundary"
        )

    monkeypatch.setattr(
        messaging,
        "process_whatsapp_inbound_message",
        forbidden_inline_processor,
    )

    handler = _Handler()
    app = portal.create_portal_app()

    handled = app.handle_api(
        "POST",
        "/api/v1/messaging/whatsapp/webhook",
        handler,
    )

    assert handled is True
    assert handler.status == 200
    assert handoffs == messages

    response = json.loads(
        handler.wfile.getvalue().decode("utf-8")
    )

    assert response["ok"] is True
    assert len(response["dispatch"]) == 2

    assert all(
        item["ok"] is True
        for item in response["dispatch"]
    )

    assert all(
        item["queued"] is True
        for item in response["dispatch"]
    )

    assert [
        item["message_id"]
        for item in response["dispatch"]
    ] == [
        "wamid.fail-one",
        "wamid.fail-two",
    ]


def test_status_only_webhook_still_acknowledges_without_dispatch(
    monkeypatch,
):
    calls: list[dict[str, str]] = []

    monkeypatch.setattr(
        messaging,
        "parse_whatsapp_inbound_messages",
        lambda _payload: [],
    )

    monkeypatch.setattr(
        messaging,
        "process_whatsapp_inbound_message",
        lambda message: calls.append(message),
    )

    handler = _Handler()
    app = portal.create_portal_app()

    handled = app.handle_api(
        "POST",
        "/api/v1/messaging/whatsapp/webhook",
        handler,
    )

    assert handled is True
    assert handler.status == 200
    assert calls == []

    response = json.loads(
        handler.wfile.getvalue().decode("utf-8")
    )

    assert response["ok"] is True
    assert response["messages"] == []
    assert response["dispatch"] == []
