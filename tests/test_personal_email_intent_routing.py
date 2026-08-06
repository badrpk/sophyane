import pytest

from sophyane.sli_personal_connector import (
    _operation,
    is_personal_connector_request,
)


@pytest.mark.parametrize(
    "query",
    [
        "what was my last outgoing email?",
        "what is my latest sent email?",
        "show my sent mail",
        "check my sent messages",
        "what was the last email I sent?",
        "show the latest message I sent",
        "open my sent folder",
        "read my most recent outgoing mail",
    ],
)
def test_sent_email_requests_use_private_connector(
    query: str,
) -> None:
    assert is_personal_connector_request(query) is True


@pytest.mark.parametrize(
    "query",
    [
        "what was my last outgoing email?",
        "what is my latest sent email?",
        "show my sent mail",
        "what was the last email I sent?",
        "show the latest message I sent",
    ],
)
def test_sent_email_requests_map_to_latest_sent(
    query: str,
) -> None:
    operation, args = _operation(query)

    assert operation == "latest_sent"
    assert args == {}


@pytest.mark.parametrize(
    "query",
    [
        "what was my last email?",
        "show my newest inbox message",
        "check my unread mail",
    ],
)
def test_incoming_email_requests_still_map_to_latest(
    query: str,
) -> None:
    assert is_personal_connector_request(query) is True

    operation, args = _operation(query)

    assert operation == "latest"
    assert args == {}


@pytest.mark.parametrize(
    "query",
    [
        "make a website about email security",
        "explain how outgoing email works",
        "what is IMAP?",
    ],
)
def test_general_email_topics_do_not_cross_private_boundary(
    query: str,
) -> None:
    assert is_personal_connector_request(query) is False


def test_generic_latest_message_is_private_but_ambiguous() -> None:
    assert (
        is_personal_connector_request(
            "show my latest message"
        )
        is True
    )
