"""Goal-completion dialogue manager for private connector results."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import webbrowser
from typing import Any, Callable

SearchCallback = Callable[[str], dict[str, Any]]

_URL_RE = re.compile(
    r"https?://[^\s<>\]\[\"']+",
    re.I,
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


def _related_query(payload: dict[str, Any]) -> str:
    subject = str(payload.get("subject") or "").strip()
    sender = str(payload.get("from") or "").strip()

    # Remove common reply/forward prefixes.
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


def _message_text(payload: dict[str, Any]) -> str:
    return (
        str(payload.get("body") or "").strip()
        or str(payload.get("preview") or "").strip()
        or "(no plain-text message body)"
    )


def _print_retrieved_message(
    payload: dict[str, Any],
) -> None:
    print()
    print("─" * 72)
    print("Retrieved private message")
    print("─" * 72)

    if payload.get("from"):
        print(f"From: {payload['from']}")

    if payload.get("to"):
        print(f"To: {payload['to']}")

    print(
        "Subject: "
        + str(
            payload.get("subject")
            or "(no subject)"
        )
    )
    print()
    print(_message_text(payload)[:4000])
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
        return formatted[:5000]

    matches = int(result.get("matches") or 0)

    return f"Related-email search completed with {matches} matches."


def continue_private_goal(
    payload: dict[str, Any],
    *,
    search_callback: SearchCallback | None = None,
) -> dict[str, Any]:
    """Ask what would complete the user's private-message request."""

    if not payload.get("ok"):
        return {
            "asked": False,
            "resolved": False,
            "action": "connector_failed",
            "summary": "The connector failed before goal completion.",
        }

    body = _message_text(payload)
    urls = _urls(payload)

    # Tests, scripts, redirected input, and explicit opt-out remain nonblocking.
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
            "summary": (
                "The retrieved message was displayed. "
                "Interactive follow-up was unavailable."
            ),
            "body": body,
        }

    _print_retrieved_message(payload)

    print()
    print("What would complete your request?")
    print()
    print("  1. This answers my request — finish")
    print("  2. Show the complete available message")

    next_number = 3
    open_number: int | None = None
    related_number: int | None = None

    if urls:
        open_number = next_number

        label = (
            "Open the GitHub Actions result"
            if "github.com" in urls[0]
            and "/actions/" in urls[0]
            else "Open the first link in the message"
        )

        print(f"  {open_number}. {label}")
        next_number += 1

    if search_callback is not None:
        related_number = next_number
        print(
            f"  {related_number}. Find related emails"
        )
        next_number += 1

    print(f"  {next_number}. Leave this unresolved for now")
    defer_number = next_number
    print()

    try:
        answer = input(
            f"Select next action [1-{defer_number}, default 1]: "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        print()

        return {
            "asked": True,
            "resolved": False,
            "action": "cancelled",
            "summary": "Follow-up selection was cancelled.",
        }

    if not answer:
        answer = "1"

    try:
        selection = int(answer)
    except ValueError:
        selection = 1

    if selection == 1:
        return {
            "asked": True,
            "resolved": True,
            "action": "confirmed_complete",
            "summary": (
                "The user confirmed that the retrieved message "
                "answered the request."
            ),
        }

    if selection == 2:
        print()
        print("Complete available message")
        print("─" * 72)
        print(body[:8000])
        print("─" * 72)

        return {
            "asked": True,
            "resolved": True,
            "action": "full_message_shown",
            "summary": "The complete available message was shown.",
            "body": body[:8000],
        }

    if open_number is not None and selection == open_number:
        opened = _open_url(urls[0])

        return {
            "asked": True,
            "resolved": opened,
            "action": "link_opened" if opened else "link_open_failed",
            "summary": (
                f"Opened: {urls[0]}"
                if opened
                else f"Could not open: {urls[0]}"
            ),
            "url": urls[0],
        }

    if (
        related_number is not None
        and selection == related_number
        and search_callback is not None
    ):
        query = _related_query(payload)
        print(f"Searching related emails for: {query}")

        result = search_callback(query)

        print()
        print(_format_search_result(result))

        return {
            "asked": True,
            "resolved": bool(result.get("ok")),
            "action": "related_emails_searched",
            "summary": (
                f"Related-email search completed for: {query}"
            ),
            "query": query,
            "search_result": result,
        }

    if selection == defer_number:
        return {
            "asked": True,
            "resolved": False,
            "action": "deferred",
            "summary": (
                "The user left the request unresolved for later."
            ),
        }

    return {
        "asked": True,
        "resolved": True,
        "action": "confirmed_complete",
        "summary": (
            "The retrieved message was treated as completing "
            "the request."
        ),
    }


__all__ = [
    "continue_private_goal",
]
