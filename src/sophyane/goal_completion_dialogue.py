"""Conversation-scoped goal-completion manager for private connector results."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import webbrowser
from typing import Any, Callable

SearchCallback = Callable[[str], dict[str, Any]]

MAX_GOAL_ACTIONS = 8

_URL_RE = re.compile(
    r"https?://[^\s<>\]\[\"']+",
    re.I,
)

# Mask likely API keys, app tokens and notification tokens before terminal display.
_LONG_SECRET_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?=[A-Za-z0-9._~-]{32,})"
    r"(?=[A-Za-z0-9._~-]*[A-Za-z])"
    r"(?=[A-Za-z0-9._~-]*[0-9])"
    r"[A-Za-z0-9._~-]{32,}"
)

_EMAIL_TOKEN_RE = re.compile(
    r"([?&](?:email_token|token|access_token|api_key)=)"
    r"([^&\s]+)",
    re.I,
)


def redact_sensitive_text(value: str) -> str:
    """Mask likely credentials while preserving ordinary message text."""
    text = str(value or "")

    text = _EMAIL_TOKEN_RE.sub(
        lambda match: match.group(1) + "[REDACTED]",
        text,
    )

    def replace_secret(match: re.Match[str]) -> str:
        token = match.group(0)

        # Preserve common non-secret URLs and identifiers.
        if token.startswith(("http", "github.com")):
            return token

        if len(token) <= 12:
            return "[REDACTED]"

        return (
            token[:6]
            + "…[REDACTED]…"
            + token[-4:]
        )

    return _LONG_SECRET_RE.sub(
        replace_secret,
        text,
    )


def _clean_url(value: str) -> str:
    return str(value or "").rstrip(".,);]}>\"'")


def _urls(payload: dict[str, Any]) -> list[str]:
    material = "\n".join(
        [
            str(payload.get("body") or ""),
            str(payload.get("preview") or ""),
            str(payload.get("subject") or ""),
        ]
    )

    found: list[str] = []

    for match in _URL_RE.findall(material):
        url = _clean_url(match)

        # Notification-management URLs often contain private tokens.
        if re.search(
            r"[?&](?:email_token|token|access_token)=",
            url,
            flags=re.I,
        ):
            continue

        if url and url not in found:
            found.append(url)

    return found[:10]


def _open_url(url: str) -> bool:
    commands: list[list[str]] = []

    if os.environ.get("WSL_DISTRO_NAME"):
        powershell = shutil.which("powershell.exe")

        if powershell:
            commands.append(
                [
                    powershell,
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    f"Start-Process '{url}'",
                ]
            )

        explorer = shutil.which("explorer.exe")

        if explorer:
            commands.append([explorer, url])

        cmd = shutil.which("cmd.exe")

        if cmd:
            commands.append(
                [
                    cmd,
                    "/c",
                    "start",
                    "",
                    url,
                ]
            )

    termux = shutil.which("termux-open-url")

    if termux:
        commands.append([termux, url])

    xdg = shutil.which("xdg-open")

    if xdg:
        commands.append([xdg, url])

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


def _message_text(payload: dict[str, Any]) -> str:
    return (
        str(payload.get("body") or "").strip()
        or str(payload.get("preview") or "").strip()
        or "(no plain-text message body)"
    )


def _related_query(payload: dict[str, Any]) -> str:
    subject = str(payload.get("subject") or "").strip()
    sender = str(payload.get("from") or "").strip()

    subject = re.sub(
        r"^(?:re|fw|fwd)\s*:\s*",
        "",
        subject,
        flags=re.I,
    )

    if subject:
        return subject[:180]

    address = re.search(
        r"[\w.+-]+@[\w.-]+",
        sender,
    )

    if address:
        return address.group(0)

    return sender[:180]


def _print_retrieved_message(
    payload: dict[str, Any],
) -> None:
    print()
    print("─" * 72)
    print("Retrieved private message")
    print("─" * 72)

    if payload.get("from"):
        print(
            "From: "
            + redact_sensitive_text(
                str(payload["from"])
            )
        )

    if payload.get("to"):
        print(
            "To: "
            + redact_sensitive_text(
                str(payload["to"])
            )
        )

    print(
        "Subject: "
        + redact_sensitive_text(
            str(
                payload.get("subject")
                or "(no subject)"
            )
        )
    )
    print()
    print(
        redact_sensitive_text(
            _message_text(payload)
        )[:5000]
    )
    print("─" * 72)


def _format_search_result(
    result: dict[str, Any],
) -> str:
    formatted = str(
        result.get("formatted")
        or result.get("message")
        or ""
    ).strip()

    if formatted:
        return redact_sensitive_text(
            formatted
        )[:6000]

    matches = int(result.get("matches") or 0)

    return (
        "Related-email search completed with "
        f"{matches} matches."
    )


def _contextual_open_label(
    url: str,
) -> str:
    lowered = url.casefold()

    if (
        "github.com" in lowered
        and "/actions/runs/" in lowered
    ):
        return "Open the GitHub Actions result"

    if "github.com" in lowered:
        return "Open the GitHub link"

    return "Open the first safe link in the message"


def _menu(
    *,
    urls: list[str],
    search_available: bool,
) -> tuple[dict[int, str], int]:
    actions: dict[int, str] = {}
    number = 1

    actions[number] = "show_full"
    print(
        f"  {number}. Show the complete available message"
    )
    number += 1

    if urls:
        actions[number] = "open_link"
        print(
            f"  {number}. {_contextual_open_label(urls[0])}"
        )
        number += 1

    if search_available:
        actions[number] = "related"
        print(f"  {number}. Find related emails")
        number += 1

    actions[number] = "finish"
    print(
        f"  {number}. My request is complete — finish"
    )
    finish_number = number
    number += 1

    actions[number] = "defer"
    print(
        f"  {number}. Leave this unresolved for now"
    )

    return actions, finish_number


def continue_private_goal(
    payload: dict[str, Any],
    *,
    search_callback: SearchCallback | None = None,
) -> dict[str, Any]:
    """Keep control until the user finishes or defers the active goal."""

    if not payload.get("ok"):
        return {
            "asked": False,
            "resolved": False,
            "action": "connector_failed",
            "actions": [],
            "summary": (
                "The connector failed before goal completion."
            ),
        }

    body = _message_text(payload)
    urls = _urls(payload)

    if (
        not sys.stdin.isatty()
        or os.environ.get(
            "SOPHYANE_DISABLE_GOAL_DIALOGUE",
            "",
        )
        == "1"
    ):
        return {
            "asked": False,
            "resolved": True,
            "action": "message_displayed",
            "actions": ["message_displayed"],
            "summary": (
                "The retrieved message was displayed. "
                "Interactive follow-up was unavailable."
            ),
            "body": redact_sensitive_text(body),
        }

    _print_retrieved_message(payload)

    action_history: list[dict[str, Any]] = []

    for action_index in range(
        1,
        MAX_GOAL_ACTIONS + 1,
    ):
        print()
        print("What would you like to do next?")
        print()

        actions, finish_number = _menu(
            urls=urls,
            search_available=(
                search_callback is not None
            ),
        )

        max_number = max(actions)

        try:
            answer = input(
                "Select next action "
                f"[1-{max_number}, "
                f"default {finish_number}]: "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            print()

            return {
                "asked": True,
                "resolved": False,
                "action": "cancelled",
                "actions": action_history,
                "summary": (
                    "The active goal session was cancelled."
                ),
            }

        if not answer:
            selection = finish_number
        else:
            try:
                selection = int(answer)
            except ValueError:
                print(
                    "Please select one of the numbered actions."
                )
                continue

        action = actions.get(selection)

        if action is None:
            print(
                "That option is not available. "
                "Please choose again."
            )
            continue

        if action == "show_full":
            print()
            print("Complete available message")
            print("─" * 72)
            print(
                redact_sensitive_text(body)[:8000]
            )
            print("─" * 72)

            action_history.append(
                {
                    "action": "full_message_shown",
                    "success": True,
                }
            )

            # Do not return: the goal session remains active.
            continue

        if action == "open_link":
            opened = _open_url(urls[0])

            if opened:
                print(f"Opened: {urls[0]}")
            else:
                print(
                    "The link could not be opened automatically."
                )

            action_history.append(
                {
                    "action": (
                        "link_opened"
                        if opened
                        else "link_open_failed"
                    ),
                    "success": opened,
                    "url": urls[0],
                }
            )

            # Opening evidence is progress, not automatic resolution.
            continue

        if action == "related":
            query = _related_query(payload)

            print(
                "Searching related emails for: "
                + query
            )

            try:
                result = search_callback(query)  # type: ignore[misc]
            except Exception as error:
                result = {
                    "ok": False,
                    "error": str(error),
                }

            print()
            print(_format_search_result(result))

            action_history.append(
                {
                    "action": "related_emails_searched",
                    "success": bool(result.get("ok")),
                    "query": query,
                }
            )

            # Search results may create another action, so remain active.
            continue

        if action == "finish":
            return {
                "asked": True,
                "resolved": True,
                "action": "confirmed_complete",
                "actions": action_history,
                "summary": (
                    "The user confirmed that the active "
                    "private-message goal was complete."
                ),
            }

        if action == "defer":
            return {
                "asked": True,
                "resolved": False,
                "action": "deferred",
                "actions": action_history,
                "summary": (
                    "The user left the active goal "
                    "unresolved for later."
                ),
            }

    return {
        "asked": True,
        "resolved": False,
        "action": "action_limit_reached",
        "actions": action_history,
        "summary": (
            "The goal session reached its bounded action limit "
            f"of {MAX_GOAL_ACTIONS} without explicit completion."
        ),
    }


__all__ = [
    "MAX_GOAL_ACTIONS",
    "continue_private_goal",
    "redact_sensitive_text",
]
