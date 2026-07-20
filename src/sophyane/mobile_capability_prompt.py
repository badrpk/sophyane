"""Compact provider prompt for permission-aware mobile capability dashboards.

The generic browser prompt keeps only the tail of long requests. Sensor and permission
contracts are both sizeable, so stacking them can remove the actual build instruction and
lead providers to return tiny placeholder HTML. This final prompt layer keeps the complete
contract short enough to survive provider limits.
"""
from __future__ import annotations

from sophyane.mobile_sensor_routing import is_mobile_sensor_request


COMPACT_CONTRACT = (
    "Create ONE complete mobile-first self-contained index.html sensor dashboard. "
    "Return raw HTML only, from <!doctype html> through </html>; no JSON or markdown. "
    "Show a Permission Center before access. From user-tapped buttons request and report "
    "Location/GPS, motion/orientation, camera, microphone and notifications separately as "
    "Prompt, Granted, Denied or Unsupported. Show live browser-accessible sensor/device data. "
    "Offer Sophyane access duration: session, 1 day, 7 days, 30 days or until revoked; store "
    "only policy/expiry in localStorage. Explain Android/browser permission lifetime is separate. "
    "On stop or expiry clear GPS watches, listeners, timers and all MediaStream tracks. Include "
    "Stop/Revoke All, feature detection, event log, responsive cards and an inline app icon."
)


def install_mobile_capability_prompt() -> None:
    """Install a concise final prompt after the general sensor/permission wrappers."""
    from sophyane import adaptive_execution as adaptive

    current = adaptive._raw_html_prompt
    if getattr(current, "_sophyane_mobile_capability_compact", False):
        return

    def prompt(original_request: str, existing: str = "") -> str:
        if not is_mobile_sensor_request(original_request):
            return current(original_request, existing)
        if existing:
            return (
                COMPACT_CONTRACT
                + " Rewrite the existing project while preserving working UI. EXISTING HTML:\n"
                + existing[:1800]
            )
        return COMPACT_CONTRACT

    setattr(prompt, "_sophyane_mobile_capability_compact", True)
    adaptive._raw_html_prompt = prompt
