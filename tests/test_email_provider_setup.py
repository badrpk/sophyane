from sophyane.email_setup_wizard import (
    detect_provider,
)


def test_gmail_detection() -> None:
    provider = detect_provider(
        "owner@gmail.com"
    )

    assert provider.provider_id == "gmail"
    assert provider.host == "imap.gmail.com"


def test_yahoo_detection() -> None:
    provider = detect_provider(
        "owner@yahoo.com"
    )

    assert provider.provider_id == "yahoo"
    assert provider.host == "imap.mail.yahoo.com"


def test_icloud_detection() -> None:
    provider = detect_provider(
        "owner@icloud.com"
    )

    assert provider.provider_id == "icloud"
    assert provider.host == "imap.mail.me.com"


def test_outlook_is_detected_as_oauth_provider() -> None:
    provider = detect_provider(
        "owner@outlook.com"
    )

    assert provider.provider_id == "outlook"
    assert provider.supports_password_setup is False


def test_unknown_domain_uses_custom_imap() -> None:
    provider = detect_provider(
        "owner@example-company.com"
    )

    assert provider.provider_id == "custom_imap"
    assert provider.host == ""
