"""Permission-center contract for generated mobile capability dashboards.

Web applications cannot choose how long Android or the browser grants a powerful
permission. They can, however, request access from a user gesture, report the real
browser state, remember a separate Sophyane consent policy, and stop collecting when
that local policy expires.
"""
from __future__ import annotations

import re
from typing import Callable

from sophyane.mobile_sensor_routing import is_mobile_sensor_request


PERMISSION_SUFFIX = (
    " Add a visible Permission Center before any sensitive access. It must list Location, "
    "Motion/Orientation, Camera, Microphone and Notifications separately with Requested, "
    "Granted, Denied, Prompt or Unsupported status. Provide one Review & Request Access "
    "button triggered by a real user tap; never start sensitive sensors automatically. "
    "Request each supported permission sequentially and explain why it is needed before "
    "the browser prompt. Use navigator.permissions.query where supported and listen for "
    "permission-state changes. For camera/microphone use getUserMedia only when selected, "
    "stop every MediaStream track when access is stopped, and never upload or store readings. "
    "Offer a Sophyane collection-policy selector: This session, 1 day, 7 days, 30 days, or "
    "Until I revoke. Save only that policy and its expiry in localStorage. Clearly explain "
    "that the browser/Android controls the actual permission lifetime and may ask again; the "
    "Sophyane duration only controls when this page is allowed to read data. On expiry, stop "
    "watchPosition, event listeners, timers and media tracks, mark access Expired, and require "
    "another user tap. Include Revoke/Stop All and Open browser site settings guidance."
)


def permission_center_problem(html: str, request: str) -> str:
    if not is_mobile_sensor_request(request):
        return ""
    lower = html.lower()
    if "permission" not in lower or not re.search(r"review.{0,40}(request|access)|request.{0,40}access", lower, re.S):
        return "mobile capability app lacks a visible permission center and user approval action"
    if "localstorage" not in lower or not any(term in lower for term in ("expiry", "expires", "expiration")):
        return "mobile capability app lacks an expiring Sophyane consent policy"
    if not any(term in lower for term in ("this session", "7 days", "30 days", "until i revoke")):
        return "mobile capability app lacks selectable consent duration options"
    if "navigator.permissions" not in lower and "permissions.query" not in lower:
        return "mobile capability app does not query browser permission state"
    if not re.search(r"stop.{0,30}(all|access|sensor)|revoke", lower, re.S):
        return "mobile capability app lacks a stop/revoke control"
    if "getusermedia" in lower and not re.search(r"\.gettracks\(\).{0,80}\.stop\(", lower, re.S):
        return "mobile capability app opens camera or microphone without stopping media tracks"
    return ""


def install_mobile_permission_center() -> None:
    """Augment prompts and deterministic validation for mobile capability requests."""
    from sophyane import adaptive_execution as adaptive

    current_prompt = adaptive._raw_html_prompt
    if not getattr(current_prompt, "_sophyane_permission_center", False):
        def prompt(original_request: str, existing: str = "") -> str:
            request = original_request
            if is_mobile_sensor_request(original_request):
                request += PERMISSION_SUFFIX
            return current_prompt(request, existing)
        setattr(prompt, "_sophyane_permission_center", True)
        adaptive._raw_html_prompt = prompt

    current_validate: Callable[[str, str], str] = adaptive._validate_html
    if not getattr(current_validate, "_sophyane_permission_center", False):
        def validate(html: str, request: str) -> str:
            problem = current_validate(html, request)
            return problem or permission_center_problem(html, request)
        setattr(validate, "_sophyane_permission_center", True)
        adaptive._validate_html = validate
