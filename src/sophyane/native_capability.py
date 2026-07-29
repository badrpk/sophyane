"""Native + combined worker chat surfaces (Sophyane policy only)."""
from __future__ import annotations


def _norm(message: str) -> str:
    return " ".join(str(message or "").lower().split())


def try_native_status_reply(message: str) -> str | None:
    t = _norm(message)
    keys = (
        "native status",
        "nifdu available",
        "neuron available",
        "native backends",
        "native workers",
        "is nifdu installed",
        "is neuron installed",
    )
    if not any(k in t for k in keys):
        return None
    from sophyane.native_backends import status_text
    return status_text()


def try_combined_workers_reply(message: str) -> str | None:
    """Prefer native combined path; may auto-fetch binaries."""
    try:
        from sophyane.collaborative_workers import try_combined_reply
    except Exception:
        return None
    return try_combined_reply(message)


def try_any_native_reply(message: str) -> str | None:
    return try_native_status_reply(message) or try_combined_workers_reply(message)
