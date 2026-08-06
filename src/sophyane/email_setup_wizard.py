"""Provider-aware, interactive email connector setup."""

from __future__ import annotations

import getpass
import imaplib
import os
import re
import shutil
import subprocess
import sys
import webbrowser
from dataclasses import dataclass
from typing import Callable

from sophyane.secret_vault import set_secret

Progress = Callable[[str], None]

_EMAIL_RE = re.compile(
    r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$",
    re.I,
)


@dataclass(frozen=True)
class EmailProvider:
    provider_id: str
    display_name: str
    host: str
    port: int = 993
    password_name: str = "app password"
    setup_url: str = ""
    supports_password_setup: bool = True
    verification_notice: str = ""


PROVIDERS = {
    "gmail": EmailProvider(
        provider_id="gmail",
        display_name="Google Gmail",
        host="imap.gmail.com",
        password_name="16-letter Google App Password",
        setup_url="https://myaccount.google.com/apppasswords",
        verification_notice=(
            "Google may first ask for your normal account password or "
            "two-step verification. This is only to verify your identity. "
            "After verification, return to the App Passwords page and "
            "create a password named Sophyane."
        ),
    ),
    "yahoo": EmailProvider(
        provider_id="yahoo",
        display_name="Yahoo Mail",
        host="imap.mail.yahoo.com",
        password_name="Yahoo app password",
        setup_url="https://login.yahoo.com/account/security",
        verification_notice=(
            "Open Account Security, choose Generate app password, and "
            "create one for Sophyane."
        ),
    ),
    "icloud": EmailProvider(
        provider_id="icloud",
        display_name="Apple iCloud Mail",
        host="imap.mail.me.com",
        password_name="Apple app-specific password",
        setup_url="https://account.apple.com/",
        verification_notice=(
            "Sign in to your Apple Account, open Sign-In and Security, "
            "then create an app-specific password for Sophyane."
        ),
    ),
    "outlook": EmailProvider(
        provider_id="outlook",
        display_name="Microsoft Outlook",
        host="outlook.office365.com",
        password_name="Microsoft app password",
        setup_url="https://account.microsoft.com/security",
        supports_password_setup=False,
        verification_notice=(
            "Microsoft commonly requires OAuth rather than a normal IMAP "
            "password. Sophyane's current IMAP connector cannot complete "
            "Microsoft OAuth yet."
        ),
    ),
}


def detect_provider(address: str) -> EmailProvider:
    domain = address.rsplit("@", 1)[-1].casefold()

    if domain in {"gmail.com", "googlemail.com"}:
        return PROVIDERS["gmail"]

    if domain in {
        "yahoo.com",
        "yahoo.co.uk",
        "ymail.com",
        "rocketmail.com",
    }:
        return PROVIDERS["yahoo"]

    if domain in {
        "icloud.com",
        "me.com",
        "mac.com",
    }:
        return PROVIDERS["icloud"]

    if domain in {
        "outlook.com",
        "hotmail.com",
        "live.com",
        "msn.com",
    }:
        return PROVIDERS["outlook"]

    return EmailProvider(
        provider_id="custom_imap",
        display_name="Custom IMAP provider",
        host="",
        password_name="IMAP password or app password",
        verification_notice=(
            "Your provider may require an app-specific password. Check "
            "its email or IMAP security documentation."
        ),
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

    return answer in {"y", "yes"}


def _open_url(url: str) -> bool:
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
            commands.append([explorer, url])

        cmd = shutil.which("cmd.exe")
        if cmd:
            commands.append([cmd, "/c", "start", "", url])

    for executable in ("termux-open-url", "xdg-open"):
        found = shutil.which(executable)
        if found:
            commands.append([found, url])

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


def _normalise_password(value: str) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _verify(
    *,
    address: str,
    password: str,
    host: str,
    port: int,
) -> tuple[bool, str]:
    connection = None

    try:
        connection = imaplib.IMAP4_SSL(
            host,
            port,
            timeout=25,
        )
        connection.login(address, password)

        status, _ = connection.select(
            "INBOX",
            readonly=True,
        )

        if status != "OK":
            return (
                False,
                "Login succeeded, but the inbox could not be opened.",
            )

        return True, "Email connection verified."

    except imaplib.IMAP4.error as error:
        return (
            False,
            f"The email provider rejected the credentials: {error}",
        )

    except OSError as error:
        return (
            False,
            f"Could not connect to {host}:{port}: {error}",
        )

    finally:
        if connection is not None:
            try:
                connection.logout()
            except Exception:
                pass


def _ask_email_address() -> str:
    for _attempt in range(3):
        try:
            address = input(
                "What is your email address? "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return ""

        if _EMAIL_RE.fullmatch(address):
            return address

        print(
            "Please enter a complete email address, for example "
            "name@gmail.com."
        )

    return ""


def _ask_custom_server() -> tuple[str, int]:
    print()
    print("Sophyane could not identify this provider automatically.")
    print("You can enter its IMAP connection details.")
    print()

    try:
        host = input(
            "What is the IMAP server? "
            "(example: imap.example.com): "
        ).strip()

        port_text = input(
            "What is the IMAP SSL port? [993]: "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return "", 993

    try:
        port = int(port_text or "993")
    except ValueError:
        port = 993

    return host, port


def configure_email_interactively(
    *,
    profile: str = "default",
    progress: Progress | None = None,
) -> dict[str, object]:
    progress = progress or (lambda _message: None)

    if not sys.stdin.isatty():
        return {
            "ok": False,
            "configured": False,
            "error": "interactive_terminal_required",
            "message": (
                "Email is not configured and this session cannot ask "
                "interactive setup questions."
            ),
        }

    print()
    print("─" * 68)
    print("Sophyane Email Setup")
    print("─" * 68)
    print(
        "Sophyane will first identify your email provider and then guide "
        "you through the correct configuration."
    )
    print()
    print("Privacy:")
    print("  • Password input is hidden.")
    print("  • Credentials are stored only in Sophyane's local vault.")
    print("  • Credentials are never sent to an LLM.")
    print("  • Public internet fallback remains blocked.")
    print()

    address = _ask_email_address()

    if not address:
        return {
            "ok": False,
            "configured": False,
            "error": "invalid_email",
            "message": "A valid email address was not provided.",
        }

    provider = detect_provider(address)

    print()
    print(f"Detected provider: {provider.display_name}")
    print(f"Email address: {address}")

    host = provider.host
    port = provider.port

    if provider.provider_id == "custom_imap":
        host, port = _ask_custom_server()

        if not host:
            return {
                "ok": False,
                "configured": False,
                "error": "imap_server_missing",
                "message": "No IMAP server was provided.",
            }

    if not provider.supports_password_setup:
        print()
        print(provider.verification_notice)

        if provider.setup_url:
            print(f"Microsoft account security: {provider.setup_url}")

        return {
            "ok": False,
            "configured": False,
            "error": "oauth_required",
            "provider": provider.provider_id,
            "message": (
                "This provider requires an OAuth connector that Sophyane "
                "does not yet support."
            ),
        }

    print()
    print(provider.verification_notice)

    if provider.setup_url:
        print()
        print(f"Provider setup page: {provider.setup_url}")

        if _yes_no(
            f"Open the {provider.display_name} setup page?",
            default=True,
        ):
            opened = _open_url(provider.setup_url)

            if opened:
                print("The provider page was opened.")
                print()
                print(
                    "Important: the page may first ask for your normal "
                    "account password or another identity check."
                )
                print(
                    "Complete that verification in the browser. Then "
                    "create the app-specific password and return here."
                )
            else:
                print(
                    "The page could not be opened automatically. Open the "
                    "address shown above manually."
                )

        try:
            input(
                "\nPress Enter after you have created the app password..."
            )
        except (EOFError, KeyboardInterrupt):
            print()
            return {
                "ok": False,
                "configured": False,
                "error": "setup_cancelled",
                "message": "Email setup was cancelled.",
            }

    for attempt in range(1, 4):
        try:
            entered = getpass.getpass(
                f"Paste the {provider.password_name} "
                "(input hidden): "
            )
        except (EOFError, KeyboardInterrupt):
            print()
            return {
                "ok": False,
                "configured": False,
                "error": "setup_cancelled",
                "message": "Email setup was cancelled.",
            }

        password = _normalise_password(entered)

        if not password:
            print("No password was entered.")
            continue

        if (
            provider.provider_id == "gmail"
            and not re.fullmatch(r"[A-Za-z]{16}", password)
        ):
            print(
                "Google App Passwords normally contain exactly 16 letters."
            )
            print(
                "Do not enter your normal Google account password here."
            )

            if attempt < 3:
                continue

        print(
            f"Testing {provider.display_name} connection "
            f"through {host}:{port}..."
        )

        verified, message = _verify(
            address=address,
            password=password,
            host=host,
            port=port,
        )

        if verified:
            for name, value in {
                "imap_user": address,
                "imap_app_password": password,
                "imap_host": host,
                "imap_port": str(port),
                "imap_provider": provider.provider_id,
            }.items():
                set_secret(profile, name, value)

            progress(
                f"{provider.display_name} credentials verified and stored "
                "in the local Sophyane vault"
            )

            print()
            print("✓ Email connection verified.")
            print("✓ Credentials saved in the local Sophyane vault.")
            print("✓ Sophyane will now continue your original request.")
            print("─" * 68)
            print()

            return {
                "ok": True,
                "configured": True,
                "email": address,
                "provider": provider.provider_id,
                "host": host,
                "port": port,
                "message": message,
            }

        print(f"✕ {message}")

        if attempt < 3:
            print(
                "Check the email address and app password, then try again."
            )

    return {
        "ok": False,
        "configured": False,
        "error": "verification_failed",
        "provider": provider.provider_id,
        "message": (
            "The email connection could not be verified after "
            "three attempts."
        ),
    }


# Compatibility with the previous Gmail-specific import.
configure_gmail_interactively = configure_email_interactively


__all__ = [
    "EmailProvider",
    "configure_email_interactively",
    "configure_gmail_interactively",
    "detect_provider",
]
