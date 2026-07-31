"""Compatibility wrappers over CapabilityRegistry gap entries."""
from __future__ import annotations

from sophyane.capability_registry import (
    gap_or_direct_reply,
    resolve_capability,
)


def is_email_access_request(message: str) -> bool:
    hit = resolve_capability(message)
    return bool(hit and hit.capability_id == "email")


def is_unavailable_external_request(message: str) -> bool:
    hit = resolve_capability(message)
    return bool(hit and not hit.available)


def capability_gap_reply(message: str) -> str | None:
    return gap_or_direct_reply(message)


EMAIL_INTEGRATION_GUIDE = """Gmail / email integration options for Sophyane:

1) Paste — paste subject/body here (no inbox access).
2) Local export — put .eml / .mbox / .txt in the workspace and ask to read that path.
3) IMAP scaffold — ask: "Scaffold a read-only IMAP script using env vars SOPHYANE_IMAP_USER and SOPHYANE_IMAP_APP_PASSWORD".
4) Full capability — set those env vars and enable an email capability (read-only last message / word count).

Security:
- Never paste the 16-character app password into chat.
- Use a Google App Password (2FA required), not your main Gmail password.
- IMAP host: imap.gmail.com (SSL).
"""


def email_gap_message() -> str:
    return (
        "I cannot read your email inbox from this session.\n"
        "No email integration is configured (IMAP/Gmail API).\n\n"
        + EMAIL_INTEGRATION_GUIDE
        + "\nReply with a full request for option 2 or 3 (not only the digit)."
    )

