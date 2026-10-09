from __future__ import annotations

import io
import json

import sophyane.cloud.messaging as messaging


def _message_payload() -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messages": [
                                {
                                    "id": "wamid.fast-ack",
                                    "from": "923001234567",
                                    "type": "text",
                                    "text": {
                                        "body": "hello async sophyane",
                                    },
                                }
                            ]
                        },
                    }
                ]
            }
        ],
    }


class _Handler:
    path = "/api/v1/messaging/whatsapp/webhook"

    def __init__(self, payload: dict):
        raw = json.dumps(
            payload,
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

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.response_headers[name] = value

    def end_headers(self):
        pass


def _response_json(handler: _Handler) -> dict:
    return json.loads(
        handler.wfile.getvalue().decode("utf-8")
    )


def test_messaging_exposes_whatsapp_inbound_handoff_seam():
    assert callable(
        getattr(
            messaging,
            "enqueue_whatsapp_inbound_message",
            None,
        )
    )


def test_webhook_hands_every_message_to_enqueue_seam(
    monkeypatch,
):
    import sophyane.cloud.portal as portal

    messages = [
        {
            "message_id": "wamid.one",
            "sender": "923001111111",
            "text": "first",
        },
        {
            "message_id": "wamid.two",
            "sender": "923002222222",
            "text": "second",
        },
    ]

    handed_off: list[dict[str, str]] = []

    monkeypatch.setattr(
        messaging,
        "parse_whatsapp_inbound_messages",
        lambda payload: messages,
    )

    monkeypatch.setattr(
        messaging,
        "enqueue_whatsapp_inbound_message",
        lambda message: (
            handed_off.append(message)
            or {
                "ok": True,
                "queued": True,
                "message_id": message["message_id"],
            }
        ),
        raising=False,
    )

    monkeypatch.setattr(
        messaging,
        "process_whatsapp_inbound_message",
        lambda message: (_ for _ in ()).throw(
            AssertionError(
                "webhook must not run slow processor inline"
            )
        ),
    )

    handler = _Handler(_message_payload())
    app = portal.create_portal_app()

    handled = app.handle_api(
        "POST",
        "/api/v1/messaging/whatsapp/webhook",
        handler,
    )

    assert handled is True
    assert handler.status == 200
    assert handed_off == messages

    body = _response_json(handler)
    assert body["ok"] is True
    assert body["messages"] == messages
    assert len(body["dispatch"]) == 2
    assert all(
        item.get("queued") is True
        for item in body["dispatch"]
    )


def test_webhook_ack_does_not_execute_slow_processor_inline(
    monkeypatch,
):
    import sophyane.cloud.portal as portal

    slow_calls: list[dict] = []
    enqueue_calls: list[dict] = []

    def forbidden_inline_processor(message):
        slow_calls.append(message)
        raise AssertionError(
            "slow WhatsApp processor executed inline"
        )

    monkeypatch.setattr(
        messaging,
        "process_whatsapp_inbound_message",
        forbidden_inline_processor,
    )

    monkeypatch.setattr(
        messaging,
        "enqueue_whatsapp_inbound_message",
        lambda message: (
            enqueue_calls.append(message)
            or {
                "ok": True,
                "queued": True,
                "message_id": message["message_id"],
            }
        ),
        raising=False,
    )

    handler = _Handler(_message_payload())
    app = portal.create_portal_app()

    handled = app.handle_api(
        "POST",
        "/api/v1/messaging/whatsapp/webhook",
        handler,
    )

    assert handled is True
    assert handler.status == 200
    assert len(enqueue_calls) == 1
    assert slow_calls == []


def test_status_only_event_acks_without_handoff(
    monkeypatch,
):
    import sophyane.cloud.portal as portal

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "statuses": [
                                {
                                    "id": "wamid.status",
                                    "status": "delivered",
                                }
                            ]
                        },
                    }
                ]
            }
        ],
    }

    enqueue_calls: list[dict] = []

    monkeypatch.setattr(
        messaging,
        "enqueue_whatsapp_inbound_message",
        lambda message: enqueue_calls.append(message),
        raising=False,
    )

    handler = _Handler(payload)
    app = portal.create_portal_app()

    handled = app.handle_api(
        "POST",
        "/api/v1/messaging/whatsapp/webhook",
        handler,
    )

    assert handled is True
    assert handler.status == 200
    assert enqueue_calls == []


def test_handoff_failure_is_contained_and_webhook_signals_retry(
    monkeypatch,
):
    import sophyane.cloud.portal as portal

    messages = [
        {
            "message_id": "wamid.bad",
            "sender": "923001111111",
            "text": "bad",
        },
        {
            "message_id": "wamid.good",
            "sender": "923002222222",
            "text": "good",
        },
    ]

    calls: list[str] = []

    monkeypatch.setattr(
        messaging,
        "parse_whatsapp_inbound_messages",
        lambda payload: messages,
    )

    def fake_enqueue(message):
        calls.append(message["message_id"])

        if message["message_id"] == "wamid.bad":
            raise RuntimeError("handoff unavailable")

        return {
            "ok": True,
            "queued": True,
            "message_id": message["message_id"],
        }

    monkeypatch.setattr(
        messaging,
        "enqueue_whatsapp_inbound_message",
        fake_enqueue,
        raising=False,
    )

    handler = _Handler(_message_payload())
    app = portal.create_portal_app()

    handled = app.handle_api(
        "POST",
        "/api/v1/messaging/whatsapp/webhook",
        handler,
    )

    assert handled is True
    assert handler.status == 503
    assert calls == ["wamid.bad", "wamid.good"]

    body = _response_json(handler)

    assert body["ok"] is False
    assert body["dispatch"][0]["ok"] is False
    assert body["dispatch"][0]["stage"] == "handoff"
    assert body["dispatch"][1]["ok"] is True


def test_fast_ack_contract_does_not_repurpose_outbound_outbox():
    import inspect

    source = inspect.getsource(
        getattr(
            messaging,
            "enqueue_whatsapp_inbound_message",
            lambda: None,
        )
    )

    if hasattr(
        messaging,
        "enqueue_whatsapp_inbound_message",
    ):
        assert "WA_OUTBOX" not in source
