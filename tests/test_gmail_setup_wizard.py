from pathlib import Path

from sophyane.email_setup_wizard import (
    _normalise_password,
    configure_email_interactively,
)
from sophyane.sli_personal_connector import (
    run_personal_connector,
)


def test_app_password_normalisation() -> None:
    assert (
        _normalise_password(
            "abcd efgh ijkl mnop"
        )
        == "abcdefghijklmnop"
    )


def test_interactive_gmail_setup_verifies_and_saves(
    monkeypatch,
) -> None:
    answers = iter([
        "owner@gmail.com",
        "n",   # Do not open browser
        "",    # App password has been created
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
        "sophyane.email_setup_wizard.sys.stdin.isatty",
        lambda: True,
    )
    monkeypatch.setattr(
        "sophyane.email_setup_wizard._verify",
        lambda **_kwargs: (
            True,
            "Email connection verified.",
        ),
    )
    monkeypatch.setattr(
        "sophyane.email_setup_wizard.set_secret",
        lambda _profile, name, value: saved.__setitem__(
            name,
            value,
        ),
    )

    result = configure_email_interactively()

    assert result["ok"] is True
    assert result["provider"] == "gmail"

    assert saved["imap_user"] == "owner@gmail.com"
    assert (
        saved["imap_app_password"]
        == "abcdefghijklmnop"
    )
    assert saved["imap_host"] == "imap.gmail.com"
    assert saved["imap_port"] == "993"
    assert saved["imap_provider"] == "gmail"


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
            "provider": "gmail",
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
        "sophyane.email_setup_wizard.sys.stdin.isatty",
        lambda: False,
    )

    result = configure_email_interactively()

    assert result["ok"] is False
    assert (
        result["error"]
        == "interactive_terminal_required"
    )


def test_outlook_setup_stops_for_oauth(
    monkeypatch,
) -> None:
    answers = iter([
        "owner@outlook.com",
    ])

    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt="": next(answers),
    )
    monkeypatch.setattr(
        "sophyane.email_setup_wizard.sys.stdin.isatty",
        lambda: True,
    )

    result = configure_email_interactively()

    assert result["ok"] is False
    assert result["provider"] == "outlook"
    assert result["error"] == "oauth_required"
