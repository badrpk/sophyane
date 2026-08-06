"""Conversational management for private email connectors."""

from __future__ import annotations

import re
import sys
from typing import Any

from sophyane.email_account_registry import (
    accounts,
    active_account,
    profile_for_email,
    register_account,
    set_active_profile,
)
from sophyane.email_setup_wizard import (
    configure_email_interactively,
)

_EMAIL_RE = re.compile(
    r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$",
    re.I,
)


def private_management_intent(
    message: str,
) -> str:
    text = " ".join(
        str(message or "")
        .casefold()
        .split()
    )

    secret_terms = (
        "app password",
        "email password",
        "gmail password",
        "imap password",
        "stored password",
    )

    if (
        any(term in text for term in secret_terms)
        and any(
            term in text
            for term in (
                "what is",
                "show",
                "tell me",
                "reveal",
                "display",
                "get my",
            )
        )
    ):
        return "reveal_secret"

    if (
        any(term in text for term in secret_terms)
        and any(
            term in text
            for term in (
                "change",
                "replace",
                "update",
                "rotate",
                "reconfigure",
                "reset",
            )
        )
    ):
        return "rotate_password"

    if any(
        phrase in text
        for phrase in (
            "add another email",
            "add additional email",
            "add one more email",
            "configure another email",
            "configure additional email",
            "connect another email",
            "second email address",
            "additional email address",
            "another email account",
        )
    ):
        return "add_account"

    if any(
        phrase in text
        for phrase in (
            "manage email accounts",
            "manage my email",
            "email accounts",
            "switch email account",
            "change active email",
            "which email is connected",
            "show connected emails",
        )
    ):
        return "manage_accounts"

    if (
        "dialog" in text
        and any(
            term in text
            for term in (
                "close",
                "closed",
                "disappear",
                "ended",
                "stop",
            )
        )
    ):
        return "explain_dialog"

    return ""


def _ask_email(
    prompt: str,
) -> str:
    for _attempt in range(3):
        try:
            value = input(prompt).strip()
        except (
            EOFError,
            KeyboardInterrupt,
        ):
            print()
            return ""

        if _EMAIL_RE.fullmatch(value):
            return value.casefold()

        print(
            "Please enter a complete email address."
        )

    return ""


def _choose_account() -> dict[str, str] | None:
    configured = accounts()

    if not configured:
        print(
            "No configured email accounts were found."
        )
        return None

    print()
    print("Configured email accounts")
    print()

    active = active_account()

    for number, item in enumerate(
        configured,
        start=1,
    ):
        marker = (
            " — active"
            if active
            and item["profile"]
            == active["profile"]
            else ""
        )

        print(
            f"  {number}. {item['email']}{marker}"
        )

    print("  0. Cancel")
    print()

    try:
        answer = input(
            f"Select account [0-{len(configured)}]: "
        ).strip()
    except (
        EOFError,
        KeyboardInterrupt,
    ):
        print()
        return None

    try:
        number = int(answer)
    except ValueError:
        return None

    if number == 0:
        return None

    if 1 <= number <= len(configured):
        return configured[number - 1]

    return None


def _configure_account(
    *,
    email: str,
    profile: str,
) -> dict[str, Any]:
    result = configure_email_interactively(
        profile=profile,
        initial_email=email,
    )

    if not result.get("ok"):
        return result

    configured_email = str(
        result.get("email")
        or email
    ).casefold()

    register_account(
        email=configured_email,
        profile=profile,
    )

    set_active_profile(profile)

    return {
        **result,
        "profile": profile,
        "active": True,
    }


def _rotate_password() -> str:
    account = _choose_account()

    if account is None:
        return "\n".join(
            [
                "Sophyane private connector management",
                "Password rotation cancelled.",
                "No secret was displayed.",
                "Success: False",
            ]
        )

    print()
    print(
        "Sophyane cannot retrieve or display the old app password."
    )
    print(
        "Create a new app password with the email provider; "
        "Sophyane will verify it and replace the stored value."
    )
    print()

    result = _configure_account(
        email=account["email"],
        profile=account["profile"],
    )

    return "\n".join(
        [
            "Sophyane private connector management",
            "Action: rotate email app password",
            f"Account: {account['email']}",
            "Old password displayed: False",
            (
                "New password verified and stored: True"
                if result.get("ok")
                else "New password verified and stored: False"
            ),
            f"Success: {bool(result.get('ok'))}",
        ]
    )


def _add_account() -> str:
    address = _ask_email(
        "What additional email address would you like to connect? "
    )

    if not address:
        return "\n".join(
            [
                "Sophyane private connector management",
                "Additional account setup cancelled.",
                "Success: False",
            ]
        )

    profile = profile_for_email(
        address
    )

    result = _configure_account(
        email=address,
        profile=profile,
    )

    return "\n".join(
        [
            "Sophyane private connector management",
            "Action: add email account",
            f"Account: {address}",
            (
                "Connection verified: True"
                if result.get("ok")
                else "Connection verified: False"
            ),
            (
                "This account is now active."
                if result.get("ok")
                else str(
                    result.get("message")
                    or "Setup was not completed."
                )
            ),
            f"Success: {bool(result.get('ok'))}",
        ]
    )


def _manage_accounts() -> str:
    configured = accounts()

    if not configured:
        if not sys.stdin.isatty():
            return "\n".join(
                [
                    "Sophyane private connector management",
                    "Configured accounts: 0",
                    "Success: False",
                ]
            )

        print(
            "No email accounts are configured."
        )

        return _add_account()

    active = active_account()

    print()
    print("Email accounts")
    print()

    for number, item in enumerate(
        configured,
        start=1,
    ):
        marker = (
            " — active"
            if active
            and active["profile"]
            == item["profile"]
            else ""
        )

        print(
            f"  {number}. {item['email']}{marker}"
        )

    print(
        f"  {len(configured) + 1}. Add another account"
    )
    print("  0. Finish")
    print()

    try:
        answer = input(
            "Select an account to make active, "
            "or choose Add: "
        ).strip()
    except (
        EOFError,
        KeyboardInterrupt,
    ):
        print()
        answer = "0"

    try:
        selection = int(answer)
    except ValueError:
        selection = 0

    if selection == len(configured) + 1:
        return _add_account()

    if 1 <= selection <= len(configured):
        selected = configured[
            selection - 1
        ]

        set_active_profile(
            selected["profile"]
        )

        return "\n".join(
            [
                "Sophyane private connector management",
                "Action: switch active email account",
                f"Active account: {selected['email']}",
                "Success: True",
            ]
        )

    return "\n".join(
        [
            "Sophyane private connector management",
            f"Configured accounts: {len(configured)}",
            (
                f"Active account: {active['email']}"
                if active
                else "Active account: none"
            ),
            "No changes made.",
            "Success: True",
        ]
    )


def handle_private_management(
    message: str,
) -> str | None:
    intent = private_management_intent(
        message
    )

    if not intent:
        return None

    if intent == "reveal_secret":
        return "\n".join(
            [
                "Sophyane private connector security",
                "Stored app passwords cannot be displayed.",
                (
                    "They are write-only credentials: Sophyane may use "
                    "them for connector authentication but must never "
                    "return them in chat or terminal output."
                ),
                (
                    "You can say: change my Gmail app password"
                ),
                (
                    "You can also say: manage my email accounts"
                ),
                "Secret disclosed: False",
                "Success: True",
            ]
        )

    if intent == "rotate_password":
        return _rotate_password()

    if intent == "add_account":
        return _add_account()

    if intent == "manage_accounts":
        return _manage_accounts()

    if intent == "explain_dialog":
        return "\n".join(
            [
                "Sophyane private connector",
                (
                    "The previous dialogue ended because the selected "
                    "connector was unavailable or the goal session had "
                    "already returned control to the main prompt."
                ),
                (
                    "A private request must not fall back to public "
                    "internet or another messaging source."
                ),
                (
                    "State your source explicitly, for example: "
                    "'show my latest WhatsApp message' or "
                    "'show my latest email'."
                ),
                "Success: True",
            ]
        )

    return None


__all__ = [
    "handle_private_management",
    "private_management_intent",
]
