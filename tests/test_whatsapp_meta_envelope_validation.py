from __future__ import annotations

import io
import json

import sophyane.cloud.messaging as messaging
import sophyane.cloud.portal as portal


WEBHOOK = "/api/v1/messaging/whatsapp/webhook"


def _message_payload() -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "business-account-id",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "id": "wamid.phase3j",
                                    "from": "923001234567",
                                    "type": "text",
                                    "text": {
                                        "body": "valid envelope",
                                    },
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def _status_payload() -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "business-account-id",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "statuses": [
                                {
                                    "id": "wamid.outbound",
                                    "status": "delivered",
                                    "recipient_id": "923001234567",
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


class _Handler:
    path = WEBHOOK

    def __init__(self, payload: object) -> None:
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

    def send_response(self, status: int) -> None:
        self.status = status

    def send_header(self, name: str, value: str) -> None:
        self.response_headers[name] = value

    def end_headers(self) -> None:
        pass


def _response(handler: _Handler) -> dict:
    raw = handler.wfile.getvalue()
    return json.loads(raw.decode("utf-8")) if raw else {}


def _post(
    monkeypatch,
    payload: object,
) -> tuple[_Handler, list[dict[str, str]]]:
    # Envelope tests are deliberately independent of cryptographic
    # authentication. Phase 3I already owns that contract.
    monkeypatch.delenv(
        "WHATSAPP_APP_SECRET",
        raising=False,
    )

    calls: list[dict[str, str]] = []

    def fake_dispatch(message: dict[str, str]) -> dict:
        calls.append(message)
        return {
            "ok": True,
            "message_id": message["message_id"],
            "sender": message["sender"],
            "reply": "isolated",
        }

    monkeypatch.setattr(
        messaging,
        "enqueue_whatsapp_inbound_message",
        fake_dispatch,
    )

    handler = _Handler(payload)
    app = portal.create_portal_app()

    handled = app.handle_api(
        "POST",
        WEBHOOK,
        handler,
    )

    assert handled is True
    return handler, calls


def test_envelope_helper_accepts_message_event():
    assert messaging.validate_whatsapp_webhook_envelope(
        _message_payload()
    ) is True


def test_envelope_helper_accepts_status_event():
    # Status notifications are legitimate WhatsApp webhook events
    # under field="messages"; they need not contain value.messages.
    assert messaging.validate_whatsapp_webhook_envelope(
        _status_payload()
    ) is True


def test_envelope_helper_rejects_wrong_object():
    payload = _message_payload()
    payload["object"] = "page"

    assert messaging.validate_whatsapp_webhook_envelope(
        payload
    ) is False


def test_envelope_helper_rejects_missing_entry():
    assert messaging.validate_whatsapp_webhook_envelope(
        {
            "object": "whatsapp_business_account",
        }
    ) is False


def test_envelope_helper_rejects_empty_entry():
    assert messaging.validate_whatsapp_webhook_envelope(
        {
            "object": "whatsapp_business_account",
            "entry": [],
        }
    ) is False


def test_envelope_helper_rejects_missing_changes():
    assert messaging.validate_whatsapp_webhook_envelope(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "business-account-id",
                }
            ],
        }
    ) is False


def test_envelope_helper_rejects_wrong_change_field():
    payload = _message_payload()
    payload["entry"][0]["changes"][0]["field"] = "feed"

    assert messaging.validate_whatsapp_webhook_envelope(
        payload
    ) is False


def test_valid_message_envelope_dispatches(
    monkeypatch,
):
    handler, calls = _post(
        monkeypatch,
        _message_payload(),
    )

    assert handler.status == 200

    body = _response(handler)

    assert body["ok"] is True
    assert calls == [
        {
            "message_id": "wamid.phase3j",
            "sender": "923001234567",
            "text": "valid envelope",
        }
    ]


def test_valid_status_envelope_acknowledges_without_dispatch(
    monkeypatch,
):
    handler, calls = _post(
        monkeypatch,
        _status_payload(),
    )

    assert handler.status == 200

    body = _response(handler)

    assert body["ok"] is True
    assert body["messages"] == []
    assert body["dispatch"] == []
    assert calls == []


def test_wrong_object_is_rejected_before_dispatch(
    monkeypatch,
):
    payload = _message_payload()
    payload["object"] = "page"

    handler, calls = _post(
        monkeypatch,
        payload,
    )

    assert handler.status == 400

    body = _response(handler)

    assert body["ok"] is False
    assert calls == []


def test_wrong_field_is_rejected_before_dispatch(
    monkeypatch,
):
    payload = _message_payload()
    payload["entry"][0]["changes"][0]["field"] = "feed"

    handler, calls = _post(
        monkeypatch,
        payload,
    )

    assert handler.status == 400

    body = _response(handler)

    assert body["ok"] is False
    assert calls == []


def test_unrelated_json_is_rejected_before_dispatch(
    monkeypatch,
):
    handler, calls = _post(
        monkeypatch,
        {
            "hello": "world",
            "messages": [
                {
                    "id": "not-meta",
                }
            ],
        },
    )

    assert handler.status == 400

    body = _response(handler)

    assert body["ok"] is False
    assert calls == []
