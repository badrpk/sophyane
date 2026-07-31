"""Gmail IMAP handler — secrets only from vault/env."""
from __future__ import annotations

import email as email_lib
import imaplib
import os
import re
from email.header import decode_header
from typing import Any

from sophyane.secret_vault import get_secret


def _creds(profile: str) -> tuple[str | None, str | None]:
    user = os.environ.get("SOPHYANE_IMAP_USER") or get_secret(profile, "imap_user")
    pw = os.environ.get("SOPHYANE_IMAP_APP_PASSWORD") or get_secret(profile, "imap_app_password")
    if pw:
        pw = pw.replace(" ", "")
    return user, pw


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
                return data.decode(part.get_content_charset() or "utf-8", errors="replace")
        return ""
    data = msg.get_payload(decode=True) or b""
    return data.decode(msg.get_content_charset() or "utf-8", errors="replace")


def execute(
    *,
    op: str,
    args: dict[str, Any],
    profile: str,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    if op != "latest":
        return {"ok": False, "error": "unknown_op", "message": f"Unsupported op: {op}"}
    user, pw = _creds(profile)
    if not user or not pw:
        return {"ok": False, "error": "not_configured", "message": "IMAP credentials missing."}
    try:
        M = imaplib.IMAP4_SSL("imap.gmail.com")
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
            f"From: {frm}\nSubject: {subj}\nWord count: {len(words)}\nPreview:\n{preview}"
        )
        M.logout()
        return {
            "ok": True,
            "from": frm,
            "subject": subj,
            "word_count": len(words),
            "formatted": formatted,
        }
    except imaplib.IMAP4.error as e:
        return {"ok": False, "error": "imap_auth", "message": f"IMAP auth failed: {e}"}
    except Exception as e:
        return {"ok": False, "error": "imap_error", "message": str(e)}
