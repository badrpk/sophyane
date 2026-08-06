from sophyane.email_account_registry import (
    active_account,
    accounts,
    register_account,
    set_active_profile,
)


def test_multiple_email_accounts(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sophyane.email_account_registry.STATE_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        "sophyane.email_account_registry.REGISTRY_FILE",
        tmp_path / "email-accounts.json",
    )
    monkeypatch.setattr(
        "sophyane.email_account_registry."
        "bootstrap_default_account",
        lambda: None,
    )

    register_account(
        email="first@gmail.com",
        profile="first@gmail.com",
    )
    register_account(
        email="second@yahoo.com",
        profile="second@yahoo.com",
    )

    set_active_profile(
        "second@yahoo.com"
    )

    configured = accounts()

    assert len(configured) == 2
    assert (
        active_account()["email"]
        == "second@yahoo.com"
    )
