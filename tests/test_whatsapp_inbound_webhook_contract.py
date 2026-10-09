from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request

import pytest

from sophyane.cloud.portal import serve_portal


WEBHOOK = "/api/v1/messaging/whatsapp/webhook"


@pytest.fixture
def portal_server():
    server = serve_portal("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address
    base_url = f"http://{host}:{port}"

    try:
        yield base_url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _request(
    url: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
) -> tuple[int, str, str]:
    data = None
    headers: dict[str, str] = {}

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return (
                response.status,
                response.headers.get("Content-Type", ""),
                response.read().decode("utf-8"),
            )
    except urllib.error.HTTPError as error:
        return (
            error.code,
            error.headers.get("Content-Type", ""),
            error.read().decode("utf-8"),
        )


def test_whatsapp_meta_verification_returns_raw_challenge(
    portal_server,
    monkeypatch,
):
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "phase3-secret")

    status, content_type, body = _request(
        portal_server
        + WEBHOOK
        + "?hub.mode=subscribe"
        + "&hub.verify_token=phase3-secret"
        + "&hub.challenge=phase3-challenge"
    )

    assert status == 200
    assert content_type.startswith("text/plain")
    assert body == "phase3-challenge"


def test_whatsapp_meta_verification_rejects_wrong_token(
    portal_server,
    monkeypatch,
):
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "phase3-secret")

    status, _content_type, body = _request(
        portal_server
        + WEBHOOK
        + "?hub.mode=subscribe"
        + "&hub.verify_token=wrong-token"
        + "&hub.challenge=must-not-be-returned"
    )

    assert status in {401, 403}
    assert body != "must-not-be-returned"


def test_whatsapp_post_extracts_meta_text_message_without_send_credentials(
    portal_server,
    monkeypatch,
):
    import sophyane.cloud.messaging as messaging

    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "phase3-secret")
    monkeypatch.delenv("WHATSAPP_CLOUD_TOKEN", raising=False)
    monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)

    monkeypatch.setattr(
        messaging,
        "process_whatsapp_inbound_message",
        lambda message: {
            "ok": True,
            "message_id": message["message_id"],
            "sender": message["sender"],
            "reply": "dispatch isolated by ingress contract",
        },
    )

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "business-account-1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15551234567",
                                "phone_number_id": "phone-number-1",
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Phase Three"},
                                    "wa_id": "923001234567",
                                }
                            ],
                            "messages": [
                                {
                                    "from": "923001234567",
                                    "id": "wamid.phase3",
                                    "timestamp": "1789840000",
                                    "type": "text",
                                    "text": {
                                        "body": "hello sophyane",
                                    },
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }

    status, content_type, body = _request(
        portal_server + WEBHOOK,
        method="POST",
        payload=payload,
    )

    assert status == 200
    assert content_type.startswith("application/json")

    result = json.loads(body)

    assert result["ok"] is True

    serialized = json.dumps(result, sort_keys=True)

    assert "wamid.phase3" in serialized
    assert "923001234567" in serialized
    assert "hello sophyane" in serialized


def test_whatsapp_post_accepts_non_message_meta_event(
    portal_server,
    monkeypatch,
):
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "phase3-secret")
    monkeypatch.delenv("WHATSAPP_CLOUD_TOKEN", raising=False)
    monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "business-account-1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "phone_number_id": "phone-number-1",
                            },
                            "statuses": [
                                {
                                    "id": "wamid.status-only",
                                    "status": "delivered",
                                    "timestamp": "1789840001",
                                    "recipient_id": "923001234567",
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }

    status, content_type, body = _request(
        portal_server + WEBHOOK,
        method="POST",
        payload=payload,
    )

    assert status == 200
    assert content_type.startswith("application/json")

    result = json.loads(body)
    assert result["ok"] is True
