from __future__ import annotations

import inspect
import json

import sophyane.cloud.messaging as messaging
import sophyane.cloud.portal as portal


VALID_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "changes": [
                {
                    "field": "messages",
                    "value": {
                        "messages": [
                            {
                                "id": "wamid.portal-retry",
                                "from": "923001234567",
                                "type": "text",
                                "text": {
                                    "body": "portal retry proof",
                                },
                            }
                        ]
                    },
                }
            ]
        }
    ],
}


class Handler:
    def __init__(self, payload=None):
        self.path = "/api/v1/messaging/whatsapp/webhook"
        self.headers = {}

        body = json.dumps(
            payload if payload is not None else VALID_PAYLOAD
        ).encode("utf-8")

        self._body = body
        self.headers["Content-Length"] = str(len(body))

        class Reader:
            def __init__(self, data):
                self.data = data

            def read(self, size=-1):
                if size < 0:
                    size = len(self.data)
                result = self.data[:size]
                self.data = self.data[size:]
                return result

        self.rfile = Reader(body)

        self.status = None
        self.response_headers = {}
        self.response_body = b""

    def send_response(self, code):
        self.status = code

    def send_header(self, key, value):
        self.response_headers[key] = value

    def end_headers(self):
        pass

    @property
    def wfile(self):
        outer = self

        class Writer:
            def write(self, data):
                outer.response_body += data

        return Writer()


def _run(monkeypatch, receipt):
    monkeypatch.setattr(
        messaging,
        "verify_whatsapp_webhook_signature",
        lambda raw_body, signature: True,
    )

    monkeypatch.setattr(
        messaging,
        "validate_whatsapp_webhook_envelope",
        lambda payload: True,
    )

    monkeypatch.setattr(
        messaging,
        "parse_whatsapp_inbound_messages",
        lambda payload: [
            {
                "message_id": "wamid.portal-retry",
                "sender": "923001234567",
                "text": "portal retry proof",
            }
        ],
    )

    monkeypatch.setattr(
        messaging,
        "enqueue_whatsapp_inbound_message",
        lambda message: dict(receipt),
    )

    app = object.__new__(portal.PortalApp)
    handler = Handler()

    app.handle_api(
        "POST",
        "/api/v1/messaging/whatsapp/webhook",
        handler,
    )

    body = {}

    if handler.response_body:
        body = json.loads(
            handler.response_body.decode("utf-8")
        )

    return handler.status, body


def test_queued_handoff_keeps_fast_ack(monkeypatch):
    status, body = _run(
        monkeypatch,
        {
            "ok": True,
            "queued": True,
            "message_id": "wamid.portal-retry",
            "sender": "923001234567",
        },
    )

    assert status == 200
    assert body["ok"] is True


def test_duplicate_handoff_keeps_fast_ack(monkeypatch):
    status, body = _run(
        monkeypatch,
        {
            "ok": True,
            "queued": False,
            "duplicate": True,
            "message_id": "wamid.portal-retry",
            "sender": "923001234567",
        },
    )

    assert status == 200
    assert body["ok"] is True


def test_backpressure_returns_retryable_non_2xx(monkeypatch):
    status, body = _run(
        monkeypatch,
        {
            "ok": False,
            "queued": False,
            "message_id": "wamid.portal-retry",
            "sender": "923001234567",
            "stage": "backpressure",
            "error": "capacity exhausted",
        },
    )

    assert status is not None
    assert 500 <= status <= 599
    assert body["ok"] is False


def test_persistence_failure_returns_retryable_non_2xx(
    monkeypatch,
):
    status, body = _run(
        monkeypatch,
        {
            "ok": False,
            "queued": False,
            "message_id": "wamid.portal-retry",
            "sender": "923001234567",
            "stage": "handoff",
            "error": "disk unavailable",
        },
    )

    assert status is not None
    assert 500 <= status <= 599
    assert body["ok"] is False


def test_executor_submission_failure_returns_non_2xx(
    monkeypatch,
):
    status, body = _run(
        monkeypatch,
        {
            "ok": False,
            "queued": False,
            "message_id": "wamid.portal-retry",
            "sender": "923001234567",
            "stage": "handoff",
            "error": "executor unavailable",
        },
    )

    assert status is not None
    assert 500 <= status <= 599
    assert body["ok"] is False


def test_unexpected_enqueue_exception_returns_non_2xx(
    monkeypatch,
):
    monkeypatch.setattr(
        messaging,
        "verify_whatsapp_webhook_signature",
        lambda raw_body, signature: True,
    )

    monkeypatch.setattr(
        messaging,
        "validate_whatsapp_webhook_envelope",
        lambda payload: True,
    )

    monkeypatch.setattr(
        messaging,
        "parse_whatsapp_inbound_messages",
        lambda payload: [
            {
                "message_id": "wamid.portal-exception",
                "sender": "923001234567",
                "text": "exception proof",
            }
        ],
    )

    def fail_enqueue(message):
        raise RuntimeError("synthetic enqueue failure")

    monkeypatch.setattr(
        messaging,
        "enqueue_whatsapp_inbound_message",
        fail_enqueue,
    )

    app = object.__new__(portal.PortalApp)
    handler = Handler()

    app.handle_api(
        "POST",
        "/api/v1/messaging/whatsapp/webhook",
        handler,
    )

    body = json.loads(
        handler.response_body.decode("utf-8")
    )

    assert handler.status is not None
    assert 500 <= handler.status <= 599
    assert body["ok"] is False


def test_retry_decision_remains_in_portal():
    source = inspect.getsource(
        portal.PortalApp.handle_api
    )

    assert "enqueue_whatsapp_inbound_message" in source

    # HTTP transport retry authority belongs at the portal boundary.
    assert (
        "backpressure" in source
        or "stage" in source
        or "queued" in source
    )


def test_retry_semantics_do_not_use_outbound_outbox():
    source = inspect.getsource(
        portal.PortalApp.handle_api
    )

    assert "WA_OUTBOX" not in source
