"""Gmail IMAP handler — secrets only from vault/env."""
from __future__ import annotations

import email as email_lib
import imaplib
import os
import re
from email.header import decode_header
from typing import Any

from sophyane.secret_vault import get_secret

STOP = {
    "the", "and", "for", "what", "which", "from", "email", "mail", "inbox",
    "see", "my", "with", "that", "this", "have", "does", "in", "on",
    "a", "an", "to", "of", "is", "are", "was", "were", "me", "i", "you",
    "last", "latest", "show", "check", "read", "please", "about",
}
# keep: company, usa, own, name, llc, inc, corp, etc.


def _creds(
    profile: str,
) -> tuple[str | None, str | None, str, int]:
    user = (
        os.environ.get("SOPHYANE_IMAP_USER")
        or get_secret(profile, "imap_user")
    )
    pw = (
        os.environ.get("SOPHYANE_IMAP_APP_PASSWORD")
        or get_secret(profile, "imap_app_password")
    )
    host = (
        os.environ.get("SOPHYANE_IMAP_HOST")
        or get_secret(profile, "imap_host")
        or "imap.gmail.com"
    )
    port_raw = (
        os.environ.get("SOPHYANE_IMAP_PORT")
        or get_secret(profile, "imap_port")
        or "993"
    )

    if pw:
        pw = pw.replace(" ", "")

    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        port = 993

    return user, pw, str(host), port


def _dec(value: str | None) -> str:
    if not value:
        return ""
    parts: list[str] = []
    for text, enc in decode_header(value):
        if isinstance(text, bytes):
            parts.append(text.decode(enc or "utf-8", errors="replace"))
        else:
            parts.append(str(text))
    return "".join(parts)


def _body(msg: email_lib.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                data = part.get_payload(decode=True) or b""
                return data.decode(
                    part.get_content_charset() or "utf-8", errors="replace"
                )
        return ""
    data = msg.get_payload(decode=True) or b""
    return data.decode(msg.get_content_charset() or "utf-8", errors="replace")


def _terms(query: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9]{2,}", query.lower())
    return [t for t in tokens if t not in STOP][:16]


def _op_latest(
    user: str,
    pw: str,
    host: str,
    port: int,
) -> dict[str, Any]:
    M = imaplib.IMAP4_SSL(host, port)
    M.login(user, pw)
    M.select("INBOX")
    typ, data = M.search(None, "ALL")
    ids = data[0].split() if data and data[0] else []
    if not ids:
        M.logout()
        return {"ok": True, "formatted": "Inbox is empty.", "empty": True}
    typ, msg_data = M.fetch(ids[-1], "(RFC822)")
    msg = email_lib.message_from_bytes(msg_data[0][1])
    body = _body(msg)
    words = re.findall(r"\b\w+\b", body)
    frm = _dec(msg.get("From"))
    subj = _dec(msg.get("Subject"))
    preview = body.strip()[:500] or "(no plain text body)"
    formatted = (
        "┌─ Latest email\n"
        f"│ From     {frm}\n"
        f"│ Subject  {subj}\n"
        f"│ Words    {len(words)}\n"
        "├─ Preview\n"
        + "\n".join("│ " + ln for ln in preview.splitlines()[:12])
        + "\n└─"
    )
    M.logout()
    return {
        "ok": True,
        "from": frm,
        "subject": subj,
        "word_count": len(words),
        "formatted": formatted,
    }


def _op_search(
    user: str,
    pw: str,
    query: str,
    host: str,
    port: int,
    limit: int = 40,
) -> dict[str, Any]:
    terms = _terms(query)
    if not terms:
        return {
            "ok": True,
            "matches": 0,
            "formatted": (
                "┌─ Email scan\n"
                "│ No useful search terms after filtering.\n"
                "│ Try names like company, LLC, Inc, or a brand.\n"
                "└─"
            ),
        }
    M = imaplib.IMAP4_SSL(host, port)
    M.login(user, pw)
    M.select("INBOX")
    typ, data = M.search(None, "ALL")
    ids = data[0].split() if data and data[0] else []
    if not ids:
        M.logout()
        return {"ok": True, "formatted": "Inbox is empty.", "matches": 0}
    ids = ids[-limit:]
    scored: list[tuple[int, str, str, str]] = []
    for num in reversed(ids):
        typ, msg_data = M.fetch(num, "(RFC822)")
        if typ != "OK" or not msg_data or not msg_data[0]:
            continue
        msg = email_lib.message_from_bytes(msg_data[0][1])
        frm = _dec(msg.get("From"))
        subj = _dec(msg.get("Subject"))
        body = _body(msg)
        blob = f"{frm}\n{subj}\n{body}".lower()
        score = sum(1 for t in terms if t in blob)
        # Prefer entity / filing / corporate mail over newsletters
        blob_l = blob
        for marker, w in (
            (" inc", 3),
            (" llc", 3),
            (" corp", 2),
            ("reinstatement", 3),
            ("good standing", 3),
            ("filing", 2),
            ("order #", 2),
        ):
            if marker in blob_l:
                score += w

        if terms and score <= 0:
            continue
        scored.append((score, frm, subj, body.strip()[:350]))
    M.logout()
    scored.sort(key=lambda x: (-x[0],))
    top = scored[:8]
    if not top:
        return {
            "ok": True,
            "matches": 0,
            "formatted": (
                "┌─ Email scan\n"
                f"│ Terms: {', '.join(terms) or '(none)'}\n"
                "│ No matches in recent messages.\n"
                "└─"
            ),
        }
    lines = [
        "┌─ Email scan (recent inbox)",
        f"│ Terms: {', '.join(terms) or '(broad scan)'}",
        f"│ Matches: {len(top)}",
    ]
    for score, frm, subj, preview in top:
        lines.append(f"│ [{score}] {subj}")
        lines.append(f"│     From: {frm}")
        for ln in preview.splitlines()[:2]:
            lines.append(f"│     {ln[:110]}")
    lines.append("└─")
    return {"ok": True, "matches": len(top), "formatted": "\n".join(lines)}



def _op_sent(
    user: str,
    pw: str,
    host: str,
    port: int,
) -> dict[str, Any]:
    """Latest message from Gmail Sent Mail (or common Sent folder names)."""
    M = imaplib.IMAP4_SSL(host, port)
    M.login(user, pw)
    candidates = (
        '"[Gmail]/Sent Mail"',
        '"[Gmail]/Sent Mail"',
        "Sent",
        "INBOX.Sent",
        '"[Google Mail]/Sent Mail"',
    )
    selected = None
    for name in candidates:
        typ, _ = M.select(name)
        if typ == "OK":
            selected = name
            break
    if not selected:
        M.logout()
        return {
            "ok": False,
            "error": "no_sent_folder",
            "message": "Could not open Gmail Sent Mail folder.",
        }
    typ, data = M.search(None, "ALL")
    ids = data[0].split() if data and data[0] else []
    if not ids:
        M.logout()
        return {"ok": True, "formatted": "Sent folder is empty.", "empty": True}
    typ, msg_data = M.fetch(ids[-1], "(RFC822)")
    msg = email_lib.message_from_bytes(msg_data[0][1])
    body = _body(msg)
    words = re.findall(r"\b\w+\b", body)
    to = _dec(msg.get("To"))
    frm = _dec(msg.get("From"))
    subj = _dec(msg.get("Subject"))
    preview = body.strip()[:500] or "(no plain text body)"
    formatted = (
        "┌─ Latest outgoing email\n"
        f"│ Folder   {selected}\n"
        f"│ From     {frm}\n"
        f"│ To       {to}\n"
        f"│ Subject  {subj}\n"
        f"│ Words    {len(words)}\n"
        "├─ Preview\n"
        + "\n".join("│ " + ln for ln in preview.splitlines()[:12])
        + "\n└─"
    )
    M.logout()
    return {
        "ok": True,
        "folder": selected,
        "from": frm,
        "to": to,
        "subject": subj,
        "word_count": len(words),
        "formatted": formatted,
    }


def execute(
    *,
    op: str,
    args: dict[str, Any],
    profile: str,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    user, pw, host, port = _creds(profile)
    if not user or not pw:
        return {
            "ok": False,
            "error": "not_configured",
            "message": "IMAP credentials missing.",
        }
    try:
        if op == "latest":
            return _op_latest(user, pw, host, port)
        if op in ("sent", "latest_sent"):
            return _op_sent(user, pw, host, port)
        if op == "search":
            query = str(args.get("query") or args.get("message") or "").strip()
            return _op_search(user, pw, query, host, port)
        return {
            "ok": False,
            "error": "unknown_op",
            "message": f"Unsupported op: {op}",
        }
    except imaplib.IMAP4.error as e:
        return {"ok": False, "error": "imap_auth", "message": f"IMAP auth failed: {e}"}
    except Exception as e:
        return {"ok": False, "error": "imap_error", "message": str(e)}
