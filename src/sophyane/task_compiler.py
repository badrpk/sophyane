"""Compile complex Sophyane requests into bounded task-specific programs.

The compiler does not execute code and does not grant authority.

Current first-class compiled workload:
- read-only Gmail correspondent aggregation

Simple operations should continue using existing deterministic capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class CompiledTask:
    task_id: str
    language: str
    filename: str
    source_code: str
    source_kind: str
    privileges: tuple[str, ...]
    expected_schema: dict[str, str]
    timeout_seconds: int = 120
    ephemeral: bool = True


_COMPLEX_MARKERS = (
    "most frequently",
    "top five",
    "top 5",
    "aggregate",
    "calculate totals",
    "group by",
    "classify",
    "reconstruct",
    "deduplicate",
    "normalize",
    "received count",
    "sent count",
    "transaction",
    "statistics",
    "summarize by month",
    "compare all",
)


def should_compile_task(request: str) -> bool:
    text = " ".join(
        str(request or "").lower().split()
    )

    if not text:
        return False

    # Explicit mutating actions remain outside this initial compiler.
    # Existing Sophyane authority handling owns those operations.
    if re.search(
        r"\b(?:send|delete|move|rename|write|modify|edit|"
        r"forward|reply to)\b",
        text,
    ):
        return False

    return any(
        marker in text
        for marker in _COMPLEX_MARKERS
    )


def _is_gmail_correspondent_task(
    request: str,
) -> bool:
    text = " ".join(
        str(request or "").lower().split()
    )

    email_context = any(
        marker in text
        for marker in (
            "email",
            "gmail",
            "mail",
            "received count",
            "sent count",
        )
    )

    correspondent_context = any(
        marker in text
        for marker in (
            "most frequently",
            "top five",
            "top 5",
            "top contacts",
            "correspondents",
            "communicate with most",
            "received count",
            "sent count",
        )
    )

    return (
        email_context
        and correspondent_context
    )


def _gmail_correspondent_program() -> str:
    # Credentials are obtained only from environment variables.
    # No secrets are embedded in generated source.
    return r'''#!/usr/bin/env python3
from __future__ import annotations

import collections
import datetime as dt
import email
from email.header import decode_header
from email.utils import getaddresses, parsedate_to_datetime
import imaplib
import json
import os
import sys


BATCH_SIZE = 200


def dec(value):
    if not value:
        return ""

    out = []

    for part, encoding in decode_header(value):
        if isinstance(part, bytes):
            out.append(
                part.decode(
                    encoding or "utf-8",
                    errors="replace",
                )
            )
        else:
            out.append(str(part))

    return "".join(out)


def parse_date(value):
    if not value:
        return None

    try:
        parsed = parsedate_to_datetime(value)
    except Exception:
        return None

    if parsed is None:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=dt.timezone.utc
        )

    return parsed.astimezone(
        dt.timezone.utc
    )


def addresses(value):
    return [
        (name.strip(), addr.lower().strip())
        for name, addr in getaddresses(
            [dec(value)]
        )
        if addr.strip()
    ]


def main():
    user = os.environ.get(
        "SOPHYANE_IMAP_USER",
        "",
    ).strip()

    password = os.environ.get(
        "SOPHYANE_IMAP_APP_PASSWORD",
        "",
    ).replace(" ", "")

    if not user or not password:
        raise SystemExit(
            "IMAP credentials missing"
        )

    days = int(
        os.environ.get(
            "SOPHYANE_TASK_WINDOW_DAYS",
            "90",
        )
    )

    output_limit = int(
        os.environ.get(
            "SOPHYANE_TASK_RESULT_LIMIT",
            "5",
        )
    )

    now = dt.datetime.now(
        dt.timezone.utc
    )

    cutoff = (
        now
        - dt.timedelta(days=days)
    )

    since = cutoff.strftime(
        "%d-%b-%Y"
    )

    client = imaplib.IMAP4_SSL(
        os.environ.get(
            "SOPHYANE_IMAP_HOST",
            "imap.gmail.com",
        ),
        int(
            os.environ.get(
                "SOPHYANE_IMAP_PORT",
                "993",
            )
        ),
    )

    client.login(
        user,
        password,
    )

    contacts = collections.defaultdict(
        lambda: {
            "received": 0,
            "sent": 0,
            "names": collections.Counter(),
        }
    )

    messages_scanned = 0

    try:
        selected = False

        for mailbox in (
            '"[Gmail]/All Mail"',
            '"[Google Mail]/All Mail"',
        ):
            typ, _ = client.select(
                mailbox,
                readonly=True,
            )

            if typ == "OK":
                selected = True
                break

        if not selected:
            raise RuntimeError(
                "Could not open Gmail All Mail"
            )

        typ, data = client.uid(
            "search",
            None,
            "SINCE",
            since,
        )

        if typ != "OK":
            raise RuntimeError(
                "IMAP search failed"
            )

        uids = (
            data[0].split()
            if data and data[0]
            else []
        )

        for offset in range(
            0,
            len(uids),
            BATCH_SIZE,
        ):
            batch = uids[
                offset:
                offset + BATCH_SIZE
            ]

            if not batch:
                continue

            uid_set = b",".join(
                batch
            ).decode(
                "ascii",
                errors="strict",
            )

            typ, raw = client.uid(
                "fetch",
                uid_set,
                "("
                "BODY.PEEK[HEADER.FIELDS "
                "(FROM TO CC BCC DATE SUBJECT)]"
                ")",
            )

            if typ != "OK":
                continue

            for item in raw or []:
                if not (
                    isinstance(item, tuple)
                    and len(item) >= 2
                    and isinstance(item[1], bytes)
                ):
                    continue

                msg = email.message_from_bytes(
                    item[1]
                )

                message_date = parse_date(
                    msg.get("Date")
                )

                # IMAP SINCE works on server/internal dates.
                # Enforce the requested RFC822 Date window too.
                if (
                    message_date is None
                    or message_date < cutoff
                    or message_date > now
                ):
                    continue

                messages_scanned += 1

                from_values = addresses(
                    msg.get("From")
                )

                to_values = addresses(
                    msg.get("To")
                )

                cc_values = addresses(
                    msg.get("Cc")
                )

                bcc_values = addresses(
                    msg.get("Bcc")
                )

                from_addresses = {
                    addr
                    for _name, addr in from_values
                }

                is_sent = (
                    user.lower()
                    in from_addresses
                )

                if is_sent:
                    # One outgoing message counts at most once
                    # per unique recipient even if they occur in
                    # To + Cc + Bcc simultaneously.
                    recipients = {}

                    for name, addr in (
                        to_values
                        + cc_values
                        + bcc_values
                    ):
                        if (
                            not addr
                            or addr == user.lower()
                        ):
                            continue

                        recipients.setdefault(
                            addr,
                            name,
                        )

                    for addr, name in recipients.items():
                        contacts[addr][
                            "sent"
                        ] += 1

                        if name:
                            contacts[addr][
                                "names"
                            ][name] += 1

                else:
                    # One received message counts once per
                    # distinct external From address.
                    seen = set()

                    for name, addr in from_values:
                        if (
                            not addr
                            or addr == user.lower()
                            or addr in seen
                        ):
                            continue

                        seen.add(addr)

                        contacts[addr][
                            "received"
                        ] += 1

                        if name:
                            contacts[addr][
                                "names"
                            ][name] += 1

    finally:
        try:
            client.logout()
        except Exception:
            pass

    results = []

    for addr, stats in contacts.items():
        received = int(
            stats["received"]
        )

        sent = int(
            stats["sent"]
        )

        total = (
            received
            + sent
        )

        common_names = [
            name
            for name, _count
            in stats["names"].most_common()
            if name
        ]

        results.append(
            {
                "email": addr,
                "name": (
                    common_names[0]
                    if common_names
                    else addr
                ),
                "received": received,
                "sent": sent,
                "total": total,
                "display_names": common_names,
            }
        )

    results.sort(
        key=lambda row: (
            row["total"],
            row["sent"],
            row["received"],
            row["email"],
        ),
        reverse=True,
    )

    payload = {
        "ok": True,
        "source": "gmail_imap_all_mail",
        "window_days": days,
        "messages_scanned": messages_scanned,
        "contacts": results[
            :output_limit
        ],
    }

    json.dump(
        payload,
        sys.stdout,
        ensure_ascii=False,
    )

    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
'''


def compile_task(
    request: str,
) -> CompiledTask | None:
    if not should_compile_task(request):
        return None

    if _is_gmail_correspondent_task(
        request
    ):
        return CompiledTask(
            task_id="gmail-top-correspondents",
            language="python",
            filename=(
                "gmail_top_correspondents.py"
            ),
            source_code=(
                _gmail_correspondent_program()
            ),
            source_kind="gmail_imap",
            privileges=("read",),
            expected_schema={
                "ok": "bool",
                "source": "str",
                "window_days": "int",
                "messages_scanned": "int",
                "contacts": "list",
            },
            timeout_seconds=180,
            ephemeral=True,
        )

    return None


__all__ = [
    "CompiledTask",
    "compile_task",
    "should_compile_task",
]
