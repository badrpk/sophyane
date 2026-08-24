"""Advanced read-only IMAP analysis for Sophyane.

Security contract:
- IMAP only.
- BODY.PEEK is used for message retrieval.
- No STORE/COPY/MOVE/EXPUNGE/APPEND.
- No SMTP.
- Attachments are never written or executed.
"""

from __future__ import annotations

import collections
import datetime as dt
import email as email_lib
import html
import imaplib
import os
import re

from email.header import decode_header
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any


DEFAULT_MAX_SCAN = 5000
HARD_MAX_SCAN = 20000
HEADER_FETCH_BATCH = 100


def _max_scan() -> int:
    """Configured safety ceiling for one mailbox scan."""
    raw = os.environ.get(
        "SOPHYANE_EMAIL_ANALYSIS_MAX_SCAN",
        str(DEFAULT_MAX_SCAN),
    )

    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_MAX_SCAN

    return max(
        1,
        min(value, HARD_MAX_SCAN),
    )


_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(
        r"\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|"
        r"password|secret)\s*[:=]\s*\S+",
        re.I,
    ),
    re.compile(r"\b\d{6}\b"),
)


def _dec(value: str | None) -> str:
    if not value:
        return ""

    result: list[str] = []

    for value_part, encoding in decode_header(value):
        if isinstance(value_part, bytes):
            result.append(
                value_part.decode(
                    encoding or "utf-8",
                    errors="replace",
                )
            )
        else:
            result.append(str(value_part))

    return "".join(result)


def _redact(value: str) -> str:
    result = str(value or "")

    for pattern in _SECRET_PATTERNS:
        result = pattern.sub("[REDACTED]", result)

    return result


def _clean_html(value: str) -> str:
    value = re.sub(
        r"(?is)<(script|style).*?>.*?</\1>",
        " ",
        value,
    )
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = html.unescape(value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n[ \t]+", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)

    return value.strip()


def _message_body(
    msg: email_lib.message.Message,
) -> str:
    plain: list[str] = []
    html_parts: list[str] = []

    parts = msg.walk() if msg.is_multipart() else [msg]

    for part in parts:
        filename = part.get_filename()

        if filename:
            continue

        ctype = part.get_content_type()

        if ctype not in {
            "text/plain",
            "text/html",
        }:
            continue

        try:
            payload = part.get_payload(decode=True) or b""

            text = payload.decode(
                part.get_content_charset() or "utf-8",
                errors="replace",
            )
        except Exception:
            continue

        if ctype == "text/plain":
            plain.append(text)
        else:
            html_parts.append(_clean_html(text))

    body = "\n".join(
        x.strip()
        for x in plain
        if x.strip()
    )

    if not body:
        body = "\n".join(
            x.strip()
            for x in html_parts
            if x.strip()
        )

    return body.strip()


def _strip_quoted(value: str) -> str:
    lines: list[str] = []

    for line in str(value or "").splitlines():
        stripped = line.strip()

        if stripped.startswith(">"):
            continue

        if re.match(
            r"^On .+ wrote:$",
            stripped,
            re.I,
        ):
            break

        if stripped in {
            "-----Original Message-----",
            "________________________________",
        }:
            break

        lines.append(line)

    return "\n".join(lines).strip()


def _parsed_date(
    msg: email_lib.message.Message,
) -> dt.datetime | None:
    value = msg.get("Date")

    if not value:
        return None

    try:
        parsed = parsedate_to_datetime(value)

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=dt.timezone.utc
            )

        return parsed
    except Exception:
        return None


def _requested_days(query: str) -> int:
    q = query.lower()

    match = re.search(
        r"(?:last|past)\s+(\d+)\s+days?",
        q,
    )

    if match:
        return max(
            1,
            min(int(match.group(1)), 3650),
        )

    match = re.search(
        r"(?:last|past)\s+(\d+)\s+months?",
        q,
    )

    if match:
        return max(
            1,
            min(int(match.group(1)) * 30, 3650),
        )

    if "six months" in q:
        return 180

    if "three months" in q:
        return 90

    return 90


def _requested_result_limit(
    query: str,
) -> int:
    """How many rows/results should be shown, not scanned."""
    q = query.lower()

    if "five most recent" in q:
        return 5

    if any(
        marker in q
        for marker in (
            "five people",
            "top five",
            "top 5",
            "five contacts",
        )
    ):
        return 5

    match = re.search(
        r"\btop\s+(\d+)\b",
        q,
    )

    if match:
        return max(
            1,
            min(int(match.group(1)), 100),
        )

    return 20


def _requested_scan_limit(
    query: str,
) -> int:
    """How much mailbox evidence must be scanned.

    Explicit message-count requests such as
    "last 200 received emails" retain their requested bound.

    Numbers describing OUTPUT cardinality, such as "five people"
    or "five most recent emails containing attachments", do not
    truncate the evidence window.
    """
    q = query.lower()

    explicit_message_window = re.search(
        r"\b(?:last|latest|recent)\s+"
        r"(\d+)\s+"
        r"(?:received\s+|sent\s+)?"
        r"(?:emails?|messages?)\b",
        q,
    )

    if explicit_message_window:
        return max(
            1,
            min(
                int(explicit_message_window.group(1)),
                _max_scan(),
            ),
        )

    return _max_scan()


def _metadata_only_query(
    query: str,
) -> bool:
    """True when aggregation only needs envelope/header metadata."""
    q = query.lower()

    return any(
        marker in q
        for marker in (
            "most frequently by email",
            "communicate with most",
            "received count",
            "sent count",
            "top email correspondents",
            "top five email contacts",
        )
    )


def _sent_folder(
    client: imaplib.IMAP4_SSL,
) -> str | None:
    candidates = (
        '"[Gmail]/Sent Mail"',
        '"[Google Mail]/Sent Mail"',
        "Sent",
        "INBOX.Sent",
    )

    for candidate in candidates:
        typ, _ = client.select(
            candidate,
            readonly=True,
        )

        if typ == "OK":
            return candidate

    return None


def _mailboxes_for_query(
    query: str,
) -> list[str]:
    q = query.lower()

    cross_mailbox = any(
        marker in q
        for marker in (
            "sent mail",
            "sent email",
            "sent messages",
            "i sent",
            "from me",
            "replied",
            "reply from me",
            "communicate with",
            "conversation",
            "thread",
            "both inbox",
            "inbox and sent",
            "received count",
            "sent count",
            "resolved",
            "unresolved",
        )
    )

    if cross_mailbox:
        return ["INBOX", "__SENT__"]

    return ["INBOX"]


def _attachments(
    msg: email_lib.message.Message,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    for part in msg.walk():
        filename = part.get_filename()

        disposition = str(
            part.get(
                "Content-Disposition",
                "",
            )
        ).lower()

        if not filename and "attachment" not in disposition:
            continue

        # We already have the RFC822 message in memory.
        # Never write or execute the attachment.
        payload = part.get_payload(decode=True)

        items.append(
            {
                "filename": _dec(filename) or "(unnamed)",
                "mime_type": part.get_content_type(),
                "size": (
                    len(payload)
                    if isinstance(payload, bytes)
                    else None
                ),
            }
        )

    return items


def _addresses(value: str | None) -> list[str]:
    return [
        addr.lower()
        for _name, addr in getaddresses(
            [value or ""]
        )
        if addr
    ]


def _normal_subject(subject: str) -> str:
    value = subject.lower().strip()

    while True:
        cleaned = re.sub(
            r"^(?:re|fw|fwd)\s*:\s*",
            "",
            value,
            flags=re.I,
        )

        if cleaned == value:
            break

        value = cleaned.strip()

    return re.sub(r"\s+", " ", value)



def _fetch_header_batch(
    client: imaplib.IMAP4_SSL,
    uids: list[bytes],
) -> list[tuple[bytes, bytes]]:
    """Fetch headers for many UIDs with one read-only IMAP request."""
    if not uids:
        return []

    uid_set = b",".join(uids).decode(
        "ascii",
        errors="strict",
    )

    typ, raw = client.uid(
        "fetch",
        uid_set,
        "("
        "BODY.PEEK[HEADER.FIELDS "
        "(FROM TO CC SUBJECT DATE "
        "MESSAGE-ID IN-REPLY-TO REFERENCES)]"
        ")",
    )

    if typ != "OK":
        return []

    messages: list[tuple[bytes, bytes]] = []

    for item in raw or []:
        if not (
            isinstance(item, tuple)
            and len(item) >= 2
            and isinstance(item[0], bytes)
            and isinstance(item[1], bytes)
        ):
            continue

        match = re.search(
            rb"\bUID\s+(\d+)\b",
            item[0],
            flags=re.I,
        )

        if not match:
            continue

        messages.append(
            (
                match.group(1),
                item[1],
            )
        )

    return messages



def _row_from_message(
    *,
    message_bytes: bytes,
    uid: bytes,
    mailbox: str,
    direction: str,
    metadata_only: bool,
) -> dict[str, Any]:
    msg = email_lib.message_from_bytes(
        message_bytes
    )

    body = (
        ""
        if metadata_only
        else _strip_quoted(
            _message_body(msg)
        )
    )

    return {
        "uid": uid.decode(
            errors="replace"
        ),
        "mailbox": mailbox,
        "direction": direction,
        "from": _dec(msg.get("From")),
        "to": _dec(msg.get("To")),
        "cc": _dec(msg.get("Cc")),
        "from_addresses": _addresses(
            msg.get("From")
        ),
        "to_addresses": _addresses(
            msg.get("To")
        ),
        "subject": _dec(
            msg.get("Subject")
        ),
        "normal_subject": _normal_subject(
            _dec(msg.get("Subject"))
        ),
        "date": _parsed_date(msg),
        "message_id": str(
            msg.get("Message-ID") or ""
        ).strip(),
        "in_reply_to": str(
            msg.get("In-Reply-To") or ""
        ).strip(),
        "references": str(
            msg.get("References") or ""
        ).strip(),
        "body": body,
        "attachments": (
            []
            if metadata_only
            else _attachments(msg)
        ),
    }

def _scan(
    user: str,
    pw: str,
    host: str,
    port: int,
    query: str,
) -> list[dict[str, Any]]:
    days = _requested_days(query)
    limit = _requested_scan_limit(query)
    metadata_only = _metadata_only_query(query)

    since = (
        dt.datetime.now(dt.timezone.utc)
        - dt.timedelta(days=days)
    ).strftime("%d-%b-%Y")

    client = imaplib.IMAP4_SSL(host, port)
    client.login(user, pw)

    rows: list[dict[str, Any]] = []

    try:
        sent = _sent_folder(client)

        for requested_box in _mailboxes_for_query(query):
            mailbox = (
                sent
                if requested_box == "__SENT__"
                else requested_box
            )

            if not mailbox:
                continue

            typ, _ = client.select(
                mailbox,
                readonly=True,
            )

            if typ != "OK":
                continue

            typ, data = client.uid(
                "search",
                None,
                "SINCE",
                since,
            )

            if typ != "OK":
                continue

            uids = (
                data[0].split()
                if data and data[0]
                else []
            )

            # Newest first, bounded.
            selected_uids = list(
                reversed(
                    uids[-limit:]
                )
            )

            direction = (
                "sent"
                if requested_box == "__SENT__"
                else "received"
            )

            if metadata_only:
                for offset in range(
                    0,
                    len(selected_uids),
                    HEADER_FETCH_BATCH,
                ):
                    batch = selected_uids[
                        offset:
                        offset + HEADER_FETCH_BATCH
                    ]

                    for uid, message_bytes in _fetch_header_batch(
                        client,
                        batch,
                    ):
                        rows.append(
                            _row_from_message(
                                message_bytes=message_bytes,
                                uid=uid,
                                mailbox=mailbox,
                                direction=direction,
                                metadata_only=True,
                            )
                        )

            else:
                for uid in selected_uids:
                    typ, raw = client.uid(
                        "fetch",
                        uid,
                        "(BODY.PEEK[])",
                    )

                    if typ != "OK":
                        continue

                    message_bytes = None

                    for item in raw or []:
                        if (
                            isinstance(item, tuple)
                            and len(item) >= 2
                            and isinstance(item[1], bytes)
                        ):
                            message_bytes = item[1]
                            break

                    if not message_bytes:
                        continue

                    rows.append(
                        _row_from_message(
                            message_bytes=message_bytes,
                            uid=uid,
                            mailbox=mailbox,
                            direction=direction,
                            metadata_only=False,
                        )
                    )


    finally:
        try:
            client.logout()
        except Exception:
            pass

    rows.sort(
        key=lambda x: (
            x["date"]
            or dt.datetime.min.replace(
                tzinfo=dt.timezone.utc
            )
        ),
        reverse=True,
    )

    return rows


def _date_text(value: Any) -> str:
    if isinstance(value, dt.datetime):
        return value.isoformat(
            sep=" ",
            timespec="minutes",
        )

    return "(unknown date)"


def _format_attachments(
    rows: list[dict[str, Any]],
    query: str,
) -> str:
    wanted = _requested_result_limit(query)

    hits = [
        row
        for row in rows
        if row["attachments"]
    ][:wanted]

    lines = [
        "┌─ Email attachment metadata",
        f"│ Matches: {len(hits)}",
    ]

    for row in hits:
        lines.extend(
            [
                f"│ Subject: {row['subject'] or '(no subject)'}",
                f"│ From: {row['from'] or '(unknown)'}",
                f"│ Date: {_date_text(row['date'])}",
            ]
        )

        for attachment in row["attachments"]:
            size = attachment["size"]

            lines.append(
                "│ Attachment: "
                f"{attachment['filename']} | "
                f"{attachment['mime_type']} | "
                + (
                    f"{size} bytes"
                    if size is not None
                    else "size unknown"
                )
            )

    lines.extend(
        [
            "│ Files written: 0",
            "│ Files executed: 0",
            "└─",
        ]
    )

    return "\n".join(lines)


def _format_correspondents(
    rows: list[dict[str, Any]],
    user: str,
) -> str:
    account = user.lower()

    counts: dict[
        str,
        dict[str, int],
    ] = collections.defaultdict(
        lambda: {
            "received": 0,
            "sent": 0,
        }
    )

    for row in rows:
        if row["direction"] == "received":
            for addr in row["from_addresses"]:
                if addr != account:
                    counts[addr]["received"] += 1

        else:
            for addr in row["to_addresses"]:
                if addr != account:
                    counts[addr]["sent"] += 1

    ranked = sorted(
        counts.items(),
        key=lambda item: -(
            item[1]["received"]
            + item[1]["sent"]
        ),
    )[:5]

    lines = [
        "┌─ Top email correspondents",
    ]

    for index, (addr, values) in enumerate(
        ranked,
        start=1,
    ):
        total = (
            values["received"]
            + values["sent"]
        )

        lines.append(
            f"│ {index}. {addr} | "
            f"received={values['received']} | "
            f"sent={values['sent']} | "
            f"total={total}"
        )

    lines.append("└─")

    return "\n".join(lines)


def _category(
    row: dict[str, Any],
) -> str:
    blob = (
        f"{row['from']} "
        f"{row['subject']} "
        f"{row['body']}"
    ).lower()

    if any(
        word in blob
        for word in (
            "security alert",
            "verification",
            "password",
            "login",
            "sign-in",
            "authentication",
            "oauth",
            "account access",
        )
    ):
        return "account/security"

    if any(
        word in blob
        for word in (
            "invoice",
            "receipt",
            "payment",
            "billing",
            "charged",
            "transaction",
            "subscription",
        )
    ):
        return "financial"

    if any(
        word in blob
        for word in (
            "order",
            "shipping",
            "delivery",
            "cart",
            "shop",
            "sale",
            "discount",
        )
    ):
        return "shopping"

    if any(
        word in blob
        for word in (
            "job",
            "meeting",
            "project",
            "client",
            "work",
            "resume",
            "application",
        )
    ):
        return "work"

    sender = row["from"].lower()

    if any(
        word in sender
        for word in (
            "noreply",
            "no-reply",
            "notification",
            "newsletter",
            "updates",
        )
    ):
        return "automated notification"

    if (
        "@" in sender
        and not any(
            word in sender
            for word in (
                "google",
                "microsoft",
                "instagram",
                "snapchat",
                "facebook",
            )
        )
    ):
        return "personal"

    return "other"


def _format_classification(
    rows: list[dict[str, Any]],
) -> str:
    rows = [
        row
        for row in rows
        if row["direction"] == "received"
    ]

    categories = (
        "personal",
        "financial",
        "account/security",
        "work",
        "shopping",
        "automated notification",
        "other",
    )

    grouped: dict[
        str,
        list[dict[str, Any]],
    ] = {
        category: []
        for category in categories
    }

    for row in rows:
        grouped[_category(row)].append(row)

    total = len(rows)

    lines = [
        "┌─ Email classification",
        f"│ Messages analyzed: {total}",
    ]

    for category in categories:
        values = grouped[category]
        pct = (
            (100.0 * len(values) / total)
            if total
            else 0.0
        )

        examples = "; ".join(
            row["subject"] or "(no subject)"
            for row in values[:3]
        )

        lines.append(
            f"│ {category}: "
            f"{len(values)} ({pct:.1f}%)"
        )

        if examples:
            lines.append(
                f"│   Examples: {_redact(examples)}"
            )

    lines.append("└─")

    return "\n".join(lines)


_AMOUNT = re.compile(
    r"(?:(USD|EUR|GBP|PKR|Rs\.?|US\$|\$|€|£)\s*)"
    r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
    re.I,
)


def _format_financial(
    rows: list[dict[str, Any]],
) -> str:
    lines = [
        "┌─ Financial email evidence",
    ]

    found = 0

    for row in rows:
        blob = (
            f"{row['subject']}\n{row['body']}"
        )

        if not re.search(
            r"\b(invoice|receipt|payment|paid|billing|charged|transaction)\b",
            blob,
            re.I,
        ):
            continue

        amounts = _AMOUNT.findall(blob)

        if not amounts:
            continue

        found += 1

        amount_text = ", ".join(
            f"{currency} {amount}"
            for currency, amount in amounts[:4]
        )

        lines.extend(
            [
                f"│ Subject: {_redact(row['subject'])}",
                f"│ Sender: {row['from']}",
                f"│ Date: {_date_text(row['date'])}",
                f"│ Amount evidence: {amount_text}",
            ]
        )

    lines.insert(
        1,
        f"│ Matching transactions/messages: {found}",
    )
    lines.append("└─")

    return "\n".join(lines)


def _thread_groups(
    rows: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    groups: dict[
        str,
        list[dict[str, Any]],
    ] = collections.defaultdict(list)

    for row in rows:
        key = (
            row["normal_subject"]
            or row["message_id"]
            or row["uid"]
        )

        groups[key].append(row)

    values = [
        sorted(
            group,
            key=lambda row: (
                row["date"]
                or dt.datetime.min.replace(
                    tzinfo=dt.timezone.utc
                )
            ),
        )
        for group in groups.values()
        if len(group) >= 2
    ]

    values.sort(
        key=lambda group: (
            group[-1]["date"]
            or dt.datetime.min.replace(
                tzinfo=dt.timezone.utc
            )
        ),
        reverse=True,
    )

    return values


def _format_thread(
    rows: list[dict[str, Any]],
) -> str:
    candidates = [
        group
        for group in _thread_groups(rows)
        if len(group) >= 3
    ]

    if not candidates:
        return (
            "┌─ Conversation reconstruction\n"
            "│ No thread with at least 3 messages "
            "was found in the scanned window.\n"
            "└─"
        )

    group = candidates[0]

    lines = [
        "┌─ Most recent conversation",
        f"│ Messages: {len(group)}",
        f"│ Subject: {group[-1]['subject']}",
    ]

    for row in group:
        who = (
            row["from"]
            if row["direction"] == "received"
            else row["to"]
        )

        lines.extend(
            [
                f"│ {_date_text(row['date'])}",
                f"│ {row['direction'].upper()}: {who}",
                "│ "
                + _redact(
                    row["body"][:300]
                ).replace("\n", " "),
            ]
        )

    if group[-1]["direction"] == "received":
        lines.append(
            "│ Status: possibly unresolved; "
            "latest thread message was received."
        )
    else:
        lines.append(
            "│ Status: likely responded; "
            "latest thread message was sent."
        )

    lines.append("└─")

    return "\n".join(lines)


def _format_unresolved(
    rows: list[dict[str, Any]],
    user: str,
) -> str:
    sent_rows = [
        row
        for row in rows
        if row["direction"] == "sent"
    ]

    received_rows = [
        row
        for row in rows
        if row["direction"] == "received"
    ]

    candidates: list[
        tuple[int, dict[str, Any], bool]
    ] = []

    for incoming in received_rows:
        blob = (
            f"{incoming['subject']} "
            f"{incoming['body']}"
        ).lower()

        needs_action = (
            "?" in incoming["body"]
            or any(
                marker in blob
                for marker in (
                    "action required",
                    "please confirm",
                    "please reply",
                    "please respond",
                    "urgent",
                    "due",
                    "required",
                    "suspended",
                    "failed",
                    "declined",
                )
            )
        )

        if not needs_action:
            continue

        incoming_date = incoming["date"]

        sender_addresses = set(
            incoming["from_addresses"]
        )

        replied = False

        for sent in sent_rows:
            if (
                incoming_date
                and sent["date"]
                and sent["date"] <= incoming_date
            ):
                continue

            if sender_addresses.intersection(
                sent["to_addresses"]
            ):
                replied = True
                break

            if (
                incoming["normal_subject"]
                and sent["normal_subject"]
                == incoming["normal_subject"]
            ):
                replied = True
                break

        score = 0

        for marker, points in (
            ("urgent", 5),
            ("suspended", 5),
            ("action required", 4),
            ("failed", 3),
            ("declined", 3),
            ("due", 2),
            ("please confirm", 2),
        ):
            if marker in blob:
                score += points

        candidates.append(
            (score, incoming, replied)
        )

    unresolved = [
        item
        for item in candidates
        if not item[2]
    ]

    unresolved.sort(
        key=lambda item: (
            -item[0],
            -(
                item[1]["date"].timestamp()
                if item[1]["date"]
                else 0
            ),
        )
    )

    lines = [
        "┌─ Unresolved email action analysis",
        f"│ Candidates: {len(candidates)}",
        f"│ Apparently unresolved: {len(unresolved)}",
    ]

    for score, row, _replied in unresolved[:20]:
        lines.extend(
            [
                f"│ Priority score: {score}",
                f"│ Date: {_date_text(row['date'])}",
                f"│ From: {row['from']}",
                f"│ Subject: {_redact(row['subject'])}",
                "│ Conclusion: no later reply from this "
                "account was found in the scanned evidence.",
                "│ Confidence: heuristic; absence of email "
                "does not prove the issue was unresolved elsewhere.",
            ]
        )

    lines.append("└─")

    return "\n".join(lines)


def _format_security_search(
    rows: list[dict[str, Any]],
) -> str:
    concepts = (
        "api",
        "credential",
        "authentication",
        "oauth",
        "password",
        "token",
        "login",
        "sign in",
        "sign-in",
        "security",
        "access",
        "verification",
        "developer",
        "key",
    )

    matches = []

    for row in rows:
        blob = (
            f"{row['subject']} "
            f"{row['body']}"
        ).lower()

        if any(
            concept in blob
            for concept in concepts
        ):
            matches.append(row)

    lines = [
        "┌─ Security/authentication email metadata",
        f"│ Matches: {len(matches)}",
    ]

    for row in matches[:40]:
        lines.extend(
            [
                f"│ Date: {_date_text(row['date'])}",
                f"│ From: {row['from']}",
                f"│ Subject: {_redact(row['subject'])}",
            ]
        )

    lines.extend(
        [
            "│ Bodies omitted.",
            "│ Secret-like values redacted.",
            "└─",
        ]
    )

    return "\n".join(lines)


def _format_generic(
    rows: list[dict[str, Any]],
) -> str:
    lines = [
        "┌─ Advanced email scan",
        f"│ Messages scanned: {len(rows)}",
    ]

    for row in rows[:20]:
        lines.extend(
            [
                f"│ [{row['direction']}] "
                f"{_date_text(row['date'])}",
                f"│ {row['subject'] or '(no subject)'}",
                f"│ From: {row['from']}",
            ]
        )

    lines.append("└─")

    return "\n".join(lines)


def analyze(
    *,
    user: str,
    pw: str,
    host: str,
    port: int,
    query: str,
) -> dict[str, Any]:
    rows = _scan(
        user,
        pw,
        host,
        port,
        query,
    )

    q = query.lower()

    if (
        "attachment" in q
        or "mime type" in q
    ):
        formatted = _format_attachments(
            rows,
            query,
        )

    elif any(
        marker in q
        for marker in (
            "five people",
            "most frequently",
            "received count",
            "sent count",
            "communicate with most",
        )
    ):
        formatted = _format_correspondents(
            rows,
            user,
        )

    elif (
        "classify" in q
        and "email" in q
    ):
        formatted = _format_classification(
            rows,
        )

    elif any(
        marker in q
        for marker in (
            "unresolved",
            "require action",
            "requires action",
            "cannot find a later sent reply",
            "whether i subsequently replied",
        )
    ):
        formatted = _format_unresolved(
            rows,
            user,
        )

    elif any(
        marker in q
        for marker in (
            "conversation",
            "reconstruct the thread",
            "thread chronologically",
        )
    ):
        formatted = _format_thread(rows)

    elif any(
        marker in q
        for marker in (
            "invoice",
            "receipt",
            "payment confirmation",
            "transactions",
        )
    ):
        formatted = _format_financial(rows)

    elif any(
        marker in q
        for marker in (
            "api keys",
            "credentials",
            "authentication",
            "oauth",
            "passwords",
            "access tokens",
        )
    ):
        formatted = _format_security_search(
            rows,
        )

    else:
        formatted = _format_generic(rows)

    return {
        "ok": True,
        "operation": "analyze",
        "messages_scanned": len(rows),
        "formatted": formatted,
    }
