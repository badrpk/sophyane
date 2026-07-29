"""Register native worker status — Sophyane-only policy surface."""
from __future__ import annotations

def ensure_native_status_capability() -> None:
    try:
        from sophyane.capability_registry import (
            CapabilitySpec,
            Priority,
            get_registry,
        )
    except Exception:
        return
    reg = get_registry()
    if any(getattr(s, "capability_id", "") == "native_status" for s in getattr(reg, "_specs", []) or getattr(reg, "specs", [])):
        return
    # Support list or dict registry internals
    try:
        specs = list(reg)
    except TypeError:
        specs = []
    priority = getattr(Priority, "LOCAL_TOOLS", 50)

    def _match(text: str) -> bool:
        t = " ".join(str(text or "").lower().split())
        keys = (
            "native status",
            "nifdu available",
            "neuron available",
            "native backends",
            "native workers",
            "is nifdu installed",
            "is neuron installed",
        )
        return any(k in t for k in keys)

    spec = CapabilitySpec(
        capability_id="native_status",
        title="Native NIFDU/Neuron status",
        route="chat",
        available=True,
        priority=priority,
        match=_match,
        gap_message=None,
    )
    if hasattr(reg, "register"):
        reg.register(spec)
    elif hasattr(reg, "add"):
        reg.add(spec)

def try_native_status_reply(message: str) -> str | None:
    ensure_native_status_capability()
    t = " ".join(str(message or "").lower().split())
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
