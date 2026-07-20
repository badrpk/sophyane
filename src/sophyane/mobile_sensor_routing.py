"""Route mobile sensor dashboard requests through verified browser generation.

A phone sensor request can be satisfied as an installable browser/PWA-style dashboard
using the browser's available motion, orientation, location, battery and network APIs.
Native-only sensors remain capability-gated by the browser and device permissions.
"""
from __future__ import annotations

from typing import Callable


_SENSOR_TERMS = (
    "sensor", "sensors", "accelerometer", "gyroscope", "orientation",
    "device motion", "device orientation", "magnetometer", "barometer",
    "proximity", "ambient light", "battery", "gps", "geolocation",
)
_MOBILE_APP_TERMS = (
    "mobile", "phone", "android", "app", "software", "icon", "dashboard",
)


def is_mobile_sensor_request(request: str) -> bool:
    text = (request or "").lower()
    return any(term in text for term in _SENSOR_TERMS) and any(term in text for term in _MOBILE_APP_TERMS)


def sensor_prompt_suffix() -> str:
    return (
        " Build this as a polished mobile-first sensor dashboard that can be opened and added to the home screen. "
        "Include a clear Start Sensors button because motion/orientation permission may require a user gesture. "
        "Show live cards for every browser-accessible capability: accelerometer/device motion, gyroscope rotation rate, "
        "device orientation/compass heading when available, geolocation, battery, network status, screen orientation, "
        "viewport, time and device/browser information. Use feature detection for every API, display Unsupported or "
        "Permission denied instead of crashing, and update values live. Add stop/reset controls and an event log. "
        "Do not claim access to native-only sensors that the browser cannot expose. Keep everything self-contained in index.html."
    )


def install_mobile_sensor_routing() -> None:
    from sophyane import adaptive_execution as adaptive

    current_browser: Callable[[str], bool] = adaptive._browser_request
    if not getattr(current_browser, "_sophyane_mobile_sensor", False):
        def browser_request(request: str) -> bool:
            return current_browser(request) or is_mobile_sensor_request(request)
        setattr(browser_request, "_sophyane_mobile_sensor", True)
        adaptive._browser_request = browser_request

    current_prompt = adaptive._raw_html_prompt
    if not getattr(current_prompt, "_sophyane_mobile_sensor", False):
        def raw_html_prompt(original_request: str, existing: str = "") -> str:
            request = original_request
            if is_mobile_sensor_request(original_request):
                request = original_request + sensor_prompt_suffix()
            return current_prompt(request, existing)
        setattr(raw_html_prompt, "_sophyane_mobile_sensor", True)
        adaptive._raw_html_prompt = raw_html_prompt
