import pytest

from sophyane.private_connector_management import (
    handle_private_management,
    private_management_intent,
)
from sophyane.sli_personal_connector import (
    is_personal_connector_request,
)


@pytest.mark.parametrize(
    ("query", "intent"),
    [
        (
            "what is my gmail app password?",
            "reveal_secret",
        ),
        (
            "show my stored IMAP password",
            "reveal_secret",
        ),
        (
            "change my gmail app password",
            "rotate_password",
        ),
        (
            "replace my email app password",
            "rotate_password",
        ),
        (
            "I want to add another email address",
            "add_account",
        ),
        (
            "configure one additional email address",
            "add_account",
        ),
        (
            "manage my email accounts",
            "manage_accounts",
        ),
        (
            "why you close dialog box",
            "explain_dialog",
        ),
    ],
)
def test_private_management_intents(
    query: str,
    intent: str,
) -> None:
    assert (
        private_management_intent(query)
        == intent
    )

    assert (
        is_personal_connector_request(query)
        is True
    )


def test_stored_password_is_never_disclosed() -> None:
    result = handle_private_management(
        "what is my gmail app password?"
    )

    assert result is not None
    assert "cannot be displayed" in result
    assert "Secret disclosed: False" in result


@pytest.mark.parametrize(
    "query",
    [
        "what is my last outgoing whatsapp message?",
        "what is my last ougoing whatsapp message?",
        "show my latest SMS",
        "show my last Snapchat message",
        "show my newest WeChat chat",
    ],
)
def test_private_message_sources_never_reach_public_route(
    query: str,
) -> None:
    assert (
        is_personal_connector_request(query)
        is True
    )
