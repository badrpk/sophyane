from __future__ import annotations

import hashlib
import hmac
import io
import json

import sophyane.cloud.messaging as messaging
import sophyane.cloud.portal as portal


WEBHOOK = "/api/v1/messaging/whatsapp/webhook"
APP_SECRET = "phase3i-app-secret"


def _signature(raw: bytes, secret: str = APP_SECRET) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        raw,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def _raw_payload(
    *,
    message_id: str = "wamid.phase3i",
    text: str = "signed hello",
) -> bytes:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messages": [
                                {
                                    "id": message_id,
                                    "from": "923001234567",
                                    "type": "text",
                                    "text": {
                                        "body": text,
                                    },
                                }
                            ]
                        },
                    }
                ]
            }
        ],
    }

    # Deliberately compact serialization. Authentication must cover
    # these exact bytes, not a parsed/reserialized representation.
    return json.dumps(
        payload,
        separators=(",", ":"),
    ).encode("utf-8")


class _Handler:
    path = WEBHOOK

    def __init__(
        self,
        raw: bytes,
        *,
        signature: str | None,
    ) -> None:
        self.headers: dict[str, str] = {
            "Content-Length": str(len(raw)),
            "Content-Type": "application/json",
        }

        if signature is not None:
            self.headers["X-Hub-Signature-256"] = signature

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

    if not raw:
        return {}

    return json.loads(raw.decode("utf-8"))


def _isolate_dispatch(monkeypatch) -> list[dict[str, str]]:
    calls: list[dict[str, str]] = []

    def fake_dispatch(message: dict[str, str]) -> dict:
        calls.append(message)
        return {
            "ok": True,
            "message_id": message["message_id"],
            "sender": message["sender"],
            "reply": "isolated signed reply",
        }

    monkeypatch.setattr(
        messaging,
        "enqueue_whatsapp_inbound_message",
        fake_dispatch,
    )

    return calls


def test_signature_helper_accepts_exact_raw_body(
    monkeypatch,
):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", APP_SECRET)

    raw = _raw_payload()

    assert messaging.verify_whatsapp_webhook_signature(
        raw,
        _signature(raw),
    ) is True


def test_signature_helper_rejects_body_tampering(
    monkeypatch,
):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", APP_SECRET)

    original = _raw_payload(text="original")
    tampered = _raw_payload(text="tampered")

    assert messaging.verify_whatsapp_webhook_signature(
        tampered,
        _signature(original),
    ) is False


def test_signature_helper_rejects_malformed_signature(
    monkeypatch,
):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", APP_SECRET)

    raw = _raw_payload()

    for supplied in (
        "",
        "not-a-signature",
        "sha1=deadbeef",
        "sha256=",
        "sha256=xyz",
    ):
        assert messaging.verify_whatsapp_webhook_signature(
            raw,
            supplied,
        ) is False


def test_signed_webhook_uses_exact_raw_bytes_and_dispatches(
    monkeypatch,
):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", APP_SECRET)

    calls = _isolate_dispatch(monkeypatch)

    raw = _raw_payload(
        message_id="wamid.valid-signature",
        text="exact bytes",
    )

    handler = _Handler(
        raw,
        signature=_signature(raw),
    )

    app = portal.create_portal_app()

    handled = app.handle_api(
        "POST",
        WEBHOOK,
        handler,
    )

    assert handled is True
    assert handler.status == 200

    body = _response(handler)

    assert body["ok"] is True
    assert calls == [
        {
            "message_id": "wamid.valid-signature",
            "sender": "923001234567",
            "text": "exact bytes",
        }
    ]


def test_webhook_rejects_signature_for_different_raw_bytes(
    monkeypatch,
):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", APP_SECRET)

    calls = _isolate_dispatch(monkeypatch)

    signed = _raw_payload(text="signed body")
    received = _raw_payload(text="modified body")

    handler = _Handler(
        received,
        signature=_signature(signed),
    )

    app = portal.create_portal_app()

    handled = app.handle_api(
        "POST",
        WEBHOOK,
        handler,
    )

    assert handled is True
    assert handler.status in {401, 403}

    body = _response(handler)

    assert body["ok"] is False
    assert calls == []


def test_webhook_rejects_missing_signature_when_secret_configured(
    monkeypatch,
):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", APP_SECRET)

    calls = _isolate_dispatch(monkeypatch)

    raw = _raw_payload(
        message_id="wamid.missing-signature",
    )

    handler = _Handler(
        raw,
        signature=None,
    )

    app = portal.create_portal_app()

    handled = app.handle_api(
        "POST",
        WEBHOOK,
        handler,
    )

    assert handled is True
    assert handler.status in {401, 403}
    assert _response(handler)["ok"] is False
    assert calls == []


def test_webhook_rejects_invalid_signature_without_dispatch(
    monkeypatch,
):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", APP_SECRET)

    calls = _isolate_dispatch(monkeypatch)

    raw = _raw_payload(
        message_id="wamid.invalid-signature",
    )

    handler = _Handler(
        raw,
        signature="sha256=" + ("0" * 64),
    )

    app = portal.create_portal_app()

    handled = app.handle_api(
        "POST",
        WEBHOOK,
        handler,
    )

    assert handled is True
    assert handler.status in {401, 403}
    assert _response(handler)["ok"] is False
    assert calls == []


def test_unsigned_webhook_remains_compatible_without_app_secret(
    monkeypatch,
):
    monkeypatch.delenv("WHATSAPP_APP_SECRET", raising=False)

    calls = _isolate_dispatch(monkeypatch)

    raw = _raw_payload(
        message_id="wamid.compatibility",
        text="legacy unsigned",
    )

    handler = _Handler(
        raw,
        signature=None,
    )

    app = portal.create_portal_app()

    handled = app.handle_api(
        "POST",
        WEBHOOK,
        handler,
    )

    assert handled is True
    assert handler.status == 200

    body = _response(handler)

    assert body["ok"] is True
    assert calls == [
        {
            "message_id": "wamid.compatibility",
            "sender": "923001234567",
            "text": "legacy unsigned",
        }
    ]
