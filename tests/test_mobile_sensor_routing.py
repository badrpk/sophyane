from sophyane import adaptive_execution as adaptive
from sophyane.mobile_sensor_routing import (
    install_mobile_sensor_routing,
    is_mobile_sensor_request,
    sensor_prompt_suffix,
)


def test_mobile_sensor_requests_are_detected() -> None:
    assert is_mobile_sensor_request("make an Android app showing all phone sensors")
    assert is_mobile_sensor_request("software with icon for live accelerometer and GPS")
    assert not is_mobile_sensor_request("make a chess game")
    assert not is_mobile_sensor_request("explain what a gyroscope is")


def test_sensor_prompt_requires_capability_gating() -> None:
    suffix = sensor_prompt_suffix().lower()
    assert "start sensors" in suffix
    assert "permission denied" in suffix
    assert "unsupported" in suffix
    assert "device motion" in suffix
    assert "geolocation" in suffix
    assert "battery" in suffix
    assert "network" in suffix
    assert "do not claim access" in suffix


def test_install_routes_sensor_request_to_browser_and_augments_prompt(monkeypatch) -> None:
    original_browser = adaptive._browser_request
    original_prompt = adaptive._raw_html_prompt
    monkeypatch.setattr(adaptive, "_browser_request", lambda request: False)
    monkeypatch.setattr(adaptive, "_raw_html_prompt", lambda request, existing="": request)

    install_mobile_sensor_routing()

    request = "make software with icon showing all sensors of my mobile"
    assert adaptive._browser_request(request)
    prompt = adaptive._raw_html_prompt(request)
    assert request in prompt
    assert "Start Sensors" in prompt
    assert "browser-accessible" in prompt

    monkeypatch.setattr(adaptive, "_browser_request", original_browser)
    monkeypatch.setattr(adaptive, "_raw_html_prompt", original_prompt)
