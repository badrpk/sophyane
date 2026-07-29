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
