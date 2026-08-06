from pathlib import Path
from unittest.mock import patch

from sophyane.gmail_setup_wizard import (
    _normalise_app_password,
    _valid_app_password,
    configure_gmail_interactively,
)
from sophyane.sli_personal_connector import (
    run_personal_connector,
)


def test_app_password_normalisation() -> None:
    assert (
        _normalise_app_password(
            "abcd efgh ijkl mnop"
        )
        == "abcdefghijklmnop"
    )

    assert _valid_app_password(
        "abcd efgh ijkl mnop"
    )


def test_invalid_app_password_is_rejected() -> None:
    assert not _valid_app_password(
        "my-normal-password"
    )
    assert not _valid_app_password(
        "1234 5678 9012 3456"
    )


def test_interactive_setup_verifies_and_saves(
    monkeypatch,
) -> None:
    answers = iter([
        "",                 # Configure now: default yes
        "owner@gmail.com",
        "n",                # Do not open browser
        "",                 # Ready
    ])

    saved: dict[str, str] = {}

    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt="": next(answers),
    )
    monkeypatch.setattr(
        "getpass.getpass",
        lambda _prompt="": "abcd efgh ijkl mnop",
    )
    monkeypatch.setattr(
        "sophyane.gmail_setup_wizard.sys.stdin.isatty",
        lambda: True,
    )
    monkeypatch.setattr(
        "sophyane.gmail_setup_wizard._verify",
        lambda _user, _password: (
            True,
            "Gmail connection verified.",
        ),
    )
    monkeypatch.setattr(
        "sophyane.gmail_setup_wizard.set_secret",
        lambda _profile, name, value: saved.__setitem__(
            name,
            value,
        ),
    )

    result = configure_gmail_interactively()

    assert result["ok"] is True
    assert saved["imap_user"] == "owner@gmail.com"
    assert (
        saved["imap_app_password"]
        == "abcdefghijklmnop"
    )


def test_connector_retries_original_request_after_setup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = {"execute": 0}

    def execute(**_kwargs):
        calls["execute"] += 1

        if calls["execute"] == 1:
            return {
                "ok": False,
                "error": "not_configured",
                "message": "IMAP credentials missing.",
            }

        return {
            "ok": True,
            "from": "Sender <sender@example.com>",
            "subject": "Latest real message",
            "word_count": 4,
            "formatted": (
                "┌─ Latest email\n"
                "│ From Sender\n"
                "│ Subject Latest real message\n"
                "├─ Preview\n"
                "│ This is real mail.\n"
                "└─"
            ),
        }

    monkeypatch.setattr(
        "sophyane.connectors.email_imap.handler.execute",
        execute,
    )
    monkeypatch.setattr(
        "sophyane.gmail_setup_wizard."
        "configure_gmail_interactively",
        lambda **_kwargs: {
            "ok": True,
            "configured": True,
        },
    )
    monkeypatch.setattr(
        "sophyane.sli_personal_connector._open_dashboard",
        lambda _workspace, _payload: "",
    )

    report = run_personal_connector(
        "what was my last email?",
        tmp_path,
    )

    assert calls["execute"] == 2
    assert "Connector verified: True" in report
    assert "Subject: Latest real message" in report
    assert "Success: True" in report


def test_noninteractive_setup_remains_fail_closed(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sophyane.gmail_setup_wizard.sys.stdin.isatty",
        lambda: False,
    )

    result = configure_gmail_interactively()

    assert result["ok"] is False
    assert (
        result["error"]
        == "interactive_terminal_required"
    )
