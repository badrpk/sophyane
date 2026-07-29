"""Deterministic replies when a requested integration is not available."""
from __future__ import annotations

import re

_EMAIL_RE = re.compile(
    r"\b("
    r"email|e-mail|inbox|gmail|outlook|imap|smtp|"
    r"mail\s+message|last\s+mail|my\s+mail"
    r")\b",
    re.I,
)

_EXTERNAL_ACCOUNT_RE = re.compile(
    r"\b("
    r"whatsapp|telegram|slack|discord|twitter|x\.com|"
    r"calendar|google\s+calendar|outlook\s+calendar|"
    r"bank\s+balance|instagram|facebook"
    r")\b",
    re.I,
)


def is_email_access_request(message: str) -> bool:
    text = " ".join(str(message or "").lower().split())
    if not text:
        return False
    if not _EMAIL_RE.search(text):
        return False
    # Prefer "access / read / last / show" intents; still catch plain "my email"
    cues = (
        "last", "latest", "recent", "show", "read", "open", "check",
        "what", "fetch", "get", "inbox", "unread",
    )
    return any(c in text for c in cues) or "my email" in text or "my e-mail" in text


def is_unavailable_external_request(message: str) -> bool:
    text = " ".join(str(message or "").lower().split())
    if is_email_access_request(text):
        return True
    return bool(_EXTERNAL_ACCOUNT_RE.search(text))


def capability_gap_reply(message: str) -> str | None:
    """Return a direct user-facing answer, or None if not a gap request."""
    text = " ".join(str(message or "").strip().split())
    if not text:
        return None
    if is_email_access_request(text):
        return (
            "I cannot read your email inbox from this session.\n\n"
            "No email integration is configured (IMAP/Gmail/Outlook API).\n\n"
            "Options:\n"
            "1. Paste the message (or subject/body) here for summary or reply help.\n"
            "2. Point me at a local export in the workspace (.eml / .mbox / .txt).\n"
            "3. Ask me to scaffold a local IMAP or Gmail read-only script.\n\n"
            "I will not enter the software-build loop for inbox access without a connector."
        )
    if _EXTERNAL_ACCOUNT_RE.search(text):
        return (
            "That needs an external account integration that is not configured "
            "in this Sophyane session. Paste the relevant text, or ask to "
            "scaffold a connector/script for your provider."
        )
    return None
