"""Interactive, privacy-safe Gmail IMAP configuration wizard."""

from __future__ import annotations

import getpass
import imaplib
import os
import re
import shutil
import subprocess
import sys
import webbrowser
from typing import Callable

from sophyane.secret_vault import set_secret

Progress = Callable[[str], None]

APP_PASSWORD_URL = "https://myaccount.google.com/apppasswords"

_EMAIL_RE = re.compile(
    r"^[A-Z0-9._%+-]+@gmail\.com$",
    re.I,
)


def _yes_no(
    prompt: str,
    *,
    default: bool = True,
) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "

    try:
        answer = input(prompt + suffix).strip().casefold()
    except (EOFError, KeyboardInterrupt):
        print()
        return False

    if not answer:
        return default

    return answer in {
        "y",
        "yes",
    }


def _open_url(url: str) -> bool:
    """Open a browser on WSL, Linux, Android/Termux, or normal Python."""
    commands: list[list[str]] = []

    if os.environ.get("WSL_DISTRO_NAME"):
        powershell = shutil.which("powershell.exe")
        if powershell:
            commands.append([
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f"Start-Process '{url}'",
            ])

        explorer = shutil.which("explorer.exe")
        if explorer:
            commands.append([
                explorer,
                url,
            ])

        cmd = shutil.which("cmd.exe")
        if cmd:
            commands.append([
                cmd,
                "/c",
                "start",
                "",
                url,
            ])

    termux = shutil.which("termux-open-url")
    if termux:
        commands.append([
            termux,
            url,
        ])

    xdg = shutil.which("xdg-open")
    if xdg:
        commands.append([
            xdg,
            url,
        ])

    for command in commands:
        try:
            subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
        except OSError:
            continue

    try:
        return bool(webbrowser.open(url, new=2))
    except Exception:
        return False


def _normalise_app_password(value: str) -> str:
    return re.sub(
        r"\s+",
        "",
        str(value or ""),
    )


def _valid_app_password(value: str) -> bool:
    # Google app passwords are normally 16 letters, displayed in groups.
    return bool(
        re.fullmatch(
            r"[A-Za-z]{16}",
            _normalise_app_password(value),
        )
    )


def _verify(
    email_address: str,
    app_password: str,
) -> tuple[bool, str]:
    connection = None

    try:
        connection = imaplib.IMAP4_SSL(
            "imap.gmail.com",
            993,
            timeout=20,
        )
        connection.login(
            email_address,
            app_password,
        )

        status, _ = connection.select(
            "INBOX",
            readonly=True,
        )

        if status != "OK":
            return (
                False,
                "Gmail login worked, but Sophyane could not open the inbox.",
            )

        return (
            True,
            "Gmail connection verified.",
        )

    except imaplib.IMAP4.error as error:
        detail = str(error)

        if "Invalid credentials" in detail:
            return (
                False,
                "Gmail rejected the app password.",
            )

        return (
            False,
            f"Gmail authentication failed: {detail}",
        )

    except OSError as error:
        return (
            False,
            f"Could not connect to Gmail: {error}",
        )

    finally:
        if connection is not None:
            try:
                connection.logout()
            except Exception:
                pass


def configure_gmail_interactively(
    *,
    profile: str = "default",
    progress: Progress | None = None,
) -> dict[str, object]:
    """Ask questions, verify Gmail, and save credentials securely."""
    progress = progress or (lambda _message: None)

    if not sys.stdin.isatty():
        return {
            "ok": False,
            "configured": False,
            "error": "interactive_terminal_required",
            "message": (
                "Gmail is not configured and this session cannot ask "
                "interactive setup questions."
            ),
        }

    print()
    print("─" * 68)
    print("Sophyane Gmail setup")
    print("─" * 68)
    print(
        "To retrieve your real email, Sophyane needs read access to Gmail "
        "through Google IMAP."
    )
    print()
    print("Privacy:")
    print("  • Your password will not be shown while you type.")
    print("  • Sophyane stores it only in its local private vault.")
    print("  • Your normal Google account password is not accepted.")
    print("  • Use a Google 16-letter App Password.")
    print()

    if not _yes_no(
        "Configure Gmail now?",
        default=True,
    ):
        return {
            "ok": False,
            "configured": False,
            "error": "setup_declined",
            "message": "Gmail setup was cancelled.",
        }

    email_address = ""

    for _attempt in range(3):
        try:
            email_address = input(
                "What is your Gmail address? "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return {
                "ok": False,
                "configured": False,
                "error": "setup_cancelled",
                "message": "Gmail setup was cancelled.",
            }

        if _EMAIL_RE.fullmatch(email_address):
            break

        print(
            "Please enter a full Gmail address, for example "
            "name@gmail.com."
        )
    else:
        return {
            "ok": False,
            "configured": False,
            "error": "invalid_email",
            "message": "A valid Gmail address was not provided.",
        }

    print()
    print("Google requires a 16-letter App Password.")
    print()
    print("To create it:")
    print("  1. Make sure 2-Step Verification is enabled on your Google account.")
    print("  2. Open Google App Passwords.")
    print("  3. Sign in if Google asks.")
    print("  4. Create an app password, for example with the name “Sophyane”.")
    print("  5. Copy the generated 16-letter password.")
    print()
    print(f"Page: {APP_PASSWORD_URL}")

    if _yes_no(
        "Open the Google App Passwords page in your browser?",
        default=True,
    ):
        opened = _open_url(APP_PASSWORD_URL)

        if opened:
            print("The Google App Passwords page was opened.")
        else:
            print(
                "The browser could not be opened automatically. "
                "Open the page shown above manually."
            )

    try:
        input(
            "\nPress Enter after you have created the App Password..."
        )
    except (EOFError, KeyboardInterrupt):
        print()
        return {
            "ok": False,
            "configured": False,
            "error": "setup_cancelled",
            "message": "Gmail setup was cancelled.",
        }

    for attempt in range(1, 4):
        try:
            entered = getpass.getpass(
                "Paste the 16-letter Gmail App Password "
                "(input hidden): "
            )
        except (EOFError, KeyboardInterrupt):
            print()
            return {
                "ok": False,
                "configured": False,
                "error": "setup_cancelled",
                "message": "Gmail setup was cancelled.",
            }

        app_password = _normalise_app_password(
            entered
        )

        if not _valid_app_password(app_password):
            print(
                "That does not look like a 16-letter Google App Password."
            )

            if attempt < 3:
                print(
                    "Spaces are allowed when pasting, but digits and "
                    "ordinary account passwords are not."
                )
                continue

            return {
                "ok": False,
                "configured": False,
                "error": "invalid_app_password_format",
                "message": (
                    "A valid 16-letter Gmail App Password "
                    "was not provided."
                ),
            }

        print("Testing Gmail connection...")

        verified, message = _verify(
            email_address,
            app_password,
        )

        if verified:
            set_secret(
                profile,
                "imap_user",
                email_address,
            )
            set_secret(
                profile,
                "imap_app_password",
                app_password,
            )

            progress(
                "Gmail IMAP credentials verified and stored "
                "in the local Sophyane vault"
            )

            print("✓ Gmail connection verified.")
            print("✓ Credentials saved in the local Sophyane vault.")
            print("✓ Sophyane will now retrieve the requested email.")
            print("─" * 68)
            print()

            return {
                "ok": True,
                "configured": True,
                "email": email_address,
                "message": message,
            }

        print(f"✕ {message}")

        if attempt < 3:
            print(
                "Check that you used a Google App Password—not your "
                "normal Gmail password—and try again."
            )

            if _yes_no(
                "Open Google App Passwords again?",
                default=False,
            ):
                _open_url(APP_PASSWORD_URL)

    return {
        "ok": False,
        "configured": False,
        "error": "verification_failed",
        "message": (
            "Gmail could not be verified after three attempts."
        ),
    }


__all__ = [
    "configure_gmail_interactively",
]
