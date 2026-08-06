from pathlib import Path

import pytest

from sophyane.sli_personal_connector import (
    _explicit_message_source,
    _is_generic_message_request,
    run_personal_connector,
)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("show my latest email", "email"),
        ("show my latest WhatsApp message", "whatsapp"),
        ("what was my last SMS?", "sms"),
        ("show my latest Snapchat message", "snapchat"),
        ("show my last WeChat message", "wechat"),
    ],
)
def test_explicit_message_source_detection(
    query: str,
    expected: str,
) -> None:
    assert _explicit_message_source(query) == expected


@pytest.mark.parametrize(
    "query",
    [
        "show my latest message",
        "what was the last message I sent?",
        "show my most recent message",
    ],
)
def test_generic_message_requests_are_ambiguous(
    query: str,
) -> None:
    assert _is_generic_message_request(query) is True


@pytest.mark.parametrize(
    "query",
    [
        "show my latest email",
        "show my latest WhatsApp message",
        "show my last SMS",
    ],
)
def test_explicit_sources_are_not_ambiguous(
    query: str,
) -> None:
    assert _is_generic_message_request(query) is False


def test_generic_message_can_select_email(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sophyane.sli_personal_connector._choose_message_source",
        lambda: "email",
    )
    monkeypatch.setattr(
        "sophyane.connectors.email_imap.handler.execute",
        lambda **_kwargs: {
            "ok": True,
            "from": "Sender <sender@example.com>",
            "to": "Owner <owner@gmail.com>",
            "subject": "Actual message",
            "word_count": 5,
            "formatted": (
                "┌─ Latest outgoing email\n"
                "│ From Sender\n"
                "│ To Owner\n"
                "│ Subject Actual message\n"
                "├─ Preview\n"
                "│ This is the real message body.\n"
                "└─"
            ),
        },
    )
    monkeypatch.setattr(
        "sophyane.sli_personal_connector._open_dashboard",
        lambda _workspace, _payload: "",
    )

    report = run_personal_connector(
        "show my latest message",
        tmp_path,
    )

    assert "Connector verified: True" in report
    assert "Message:" in report
    assert "This is the real message body." in report


def test_whatsapp_selection_does_not_substitute_email(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sophyane.sli_personal_connector._choose_message_source",
        lambda: "whatsapp",
    )

    report = run_personal_connector(
        "show my latest message",
        tmp_path,
    )

    assert "Selected source: WhatsApp" in report
    assert "Connector available: False" in report
    assert "will not substitute email" in report
    assert "Success: False" in report
