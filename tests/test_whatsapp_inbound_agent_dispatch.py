from __future__ import annotations

import sophyane.cloud.messaging as messaging


def test_whatsapp_inbound_text_reaches_conversation_and_sender_gets_reply(
    monkeypatch,
):
    conversation_calls: list[str] = []
    send_calls: list[tuple[str, str]] = []

    def fake_conversation_reply(message: str) -> str:
        conversation_calls.append(message)
        return "Sophyane reply from conversation seam"

    def fake_send_whatsapp(
        to: str,
        text: str,
    ) -> dict:
        send_calls.append((to, text))
        return {
            "ok": True,
            "channel": "whatsapp",
            "to": to,
        }

    monkeypatch.setattr(
        messaging,
        "_whatsapp_conversation_reply",
        fake_conversation_reply,
        raising=False,
    )
    monkeypatch.setattr(
        messaging,
        "send_whatsapp",
        fake_send_whatsapp,
    )

    result = messaging.process_whatsapp_inbound_message(
        {
            "message_id": "wamid.dispatch-proof",
            "sender": "923001234567",
            "text": "hello from whatsapp",
        }
    )

    assert conversation_calls == ["hello from whatsapp"]

    assert send_calls == [
        (
            "923001234567",
            "Sophyane reply from conversation seam",
        )
    ]

    assert result["ok"] is True
    assert result["message_id"] == "wamid.dispatch-proof"
    assert result["sender"] == "923001234567"
    assert result["reply"] == "Sophyane reply from conversation seam"


def test_whatsapp_dispatch_uses_existing_chat_reply_behavior(
    monkeypatch,
):
    import sophyane.cloud.telegram_bot as telegram_bot

    calls: list[tuple[str, str, str]] = []

    def fake_chat_reply(
        message: str,
        *,
        email: str = "",
        plan: str = "free",
    ) -> str:
        calls.append((message, email, plan))
        return "existing conversation reply"

    monkeypatch.setattr(
        telegram_bot,
        "_chat_reply",
        fake_chat_reply,
    )

    reply = messaging._whatsapp_conversation_reply(
        "ordinary whatsapp conversation"
    )

    assert reply == "existing conversation reply"
    assert calls == [
        (
            "ordinary whatsapp conversation",
            "",
            "free",
        )
    ]


def test_whatsapp_dispatch_does_not_enter_repository_execution_for_normal_chat(
    monkeypatch,
):
    import sophyane.human_conversation_cli as human_cli

    def forbidden_repository_execution(*args, **kwargs):
        raise AssertionError(
            "ordinary WhatsApp chat entered repository execution"
        )

    monkeypatch.setattr(
        human_cli,
        "_execute_repository_request",
        forbidden_repository_execution,
    )

    monkeypatch.setattr(
        messaging,
        "send_whatsapp",
        lambda to, text: {
            "ok": True,
            "channel": "whatsapp",
            "to": to,
        },
    )

    monkeypatch.setattr(
        messaging,
        "_whatsapp_conversation_reply",
        lambda message: "normal conversational reply",
        raising=False,
    )

    result = messaging.process_whatsapp_inbound_message(
        {
            "message_id": "wamid.normal-chat",
            "sender": "923009999999",
            "text": "How are you today?",
        }
    )

    assert result["ok"] is True
    assert result["reply"] == "normal conversational reply"


def test_whatsapp_webhook_dispatches_every_parsed_text_message(
    monkeypatch,
):
    import sophyane.cloud.portal as portal

    parsed_messages = [
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

    handoff_calls: list[dict[str, str]] = []

    monkeypatch.setattr(
        messaging,
        "parse_whatsapp_inbound_messages",
        lambda payload: parsed_messages,
    )

    def fake_enqueue(
        message: dict[str, str],
    ) -> dict:
        handoff_calls.append(message)

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
            "webhook must hand off parsed messages "
            "instead of processing them inline"
        )

    monkeypatch.setattr(
        messaging,
        "process_whatsapp_inbound_message",
        forbidden_inline_processor,
        raising=False,
    )

    class Handler:
        path = "/api/v1/messaging/whatsapp/webhook"

        def __init__(self):
            import io

            raw = (
                b'{"object":"whatsapp_business_account",'
                b'"entry":[{"changes":[{"field":"messages",'
                b'"value":{"statuses":[]}}]}]}'
            )

            self.headers = {
                "Content-Length": str(len(raw)),
                "Content-Type": "application/json",
            }
            self.rfile = io.BytesIO(raw)
            self.wfile = io.BytesIO()
            self.status = None
            self.response_headers = {}

        def send_response(self, status):
            self.status = status

        def send_header(self, name, value):
            self.response_headers[name] = value

        def end_headers(self):
            pass

    handler = Handler()
    app = portal.create_portal_app()

    handled = app.handle_api(
        "POST",
        "/api/v1/messaging/whatsapp/webhook",
        handler,
    )

    assert handled is True
    assert handler.status == 200

    assert handoff_calls == parsed_messages

    import json

    response = json.loads(
        handler.wfile.getvalue().decode("utf-8")
    )

    assert response["ok"] is True
    assert response["messages"] == parsed_messages

    assert response["dispatch"] == [
        {
            "ok": True,
            "queued": True,
            "message_id": "wamid.one",
            "sender": "923001111111",
        },
        {
            "ok": True,
            "queued": True,
            "message_id": "wamid.two",
            "sender": "923002222222",
        },
    ]


def test_whatsapp_status_only_event_does_not_dispatch_agent(
    monkeypatch,
):
    import sophyane.cloud.portal as portal

    calls: list[dict] = []

    monkeypatch.setattr(
        messaging,
        "parse_whatsapp_inbound_messages",
        lambda payload: [],
    )

    monkeypatch.setattr(
        messaging,
        "process_whatsapp_inbound_message",
        lambda message: calls.append(message),
        raising=False,
    )

    class Handler:
        path = "/api/v1/messaging/whatsapp/webhook"

        def __init__(self):
            import io

            raw = (
                b'{"object":"whatsapp_business_account",'
                b'"entry":[{"changes":[{"field":"messages",'
                b'"value":{"statuses":[]}}]}]}'
            )
            self.headers = {
                "Content-Length": str(len(raw)),
                "Content-Type": "application/json",
            }
            self.rfile = io.BytesIO(raw)
            self.wfile = io.BytesIO()
            self.status = None
            self.response_headers = {}

        def send_response(self, status):
            self.status = status

        def send_header(self, name, value):
            self.response_headers[name] = value

        def end_headers(self):
            pass

    handler = Handler()
    app = portal.create_portal_app()

    handled = app.handle_api(
        "POST",
        "/api/v1/messaging/whatsapp/webhook",
        handler,
    )

    assert handled is True
    assert handler.status == 200
    assert calls == []
