from __future__ import annotations

import json
import threading
import urllib.request

import sophyane.hardware_api as hardware_api


def _sensor_report():
    return {
        "ok": True,
        "platform": {
            "termux": True,
            "termux_version": "googleplay.2026.06.21",
            "google_play_termux": True,
        },
        "capabilities": {
            "camera_capture": {
                "id": "camera_capture",
                "command": "termux-camera-photo",
                "command_path": "/mock/termux-camera-photo",
                "command_present": True,
                "available": False,
                "verified": True,
                "backend": None,
                "reason": "google_play_termux_api_unavailable",
            },
            "microphone_capture": {
                "id": "microphone_capture",
                "command": "termux-microphone-record",
                "command_path": "/mock/termux-microphone-record",
                "command_present": True,
                "available": False,
                "verified": False,
                "backend": None,
                "reason": "active_probe_required",
            },
        },
        "verification_policy":
            "command_presence_is_not_runtime_sensor_evidence",
        "active_probe_required": True,
    }


def test_hardware_api_sensors_returns_native_sensor_truth(
    monkeypatch,
):
    monkeypatch.setattr(
        hardware_api,
        "native_sensor_capabilities",
        _sensor_report,
        raising=False,
    )

    api = hardware_api.HardwareAPI()

    result = api.sensors()

    assert result["ok"] is True
    assert (
        result["capabilities"]["camera_capture"]["reason"]
        == "google_play_termux_api_unavailable"
    )
    assert (
        result["capabilities"]["microphone_capture"]["reason"]
        == "active_probe_required"
    )


def test_hardware_api_dispatch_supports_sensors(
    monkeypatch,
):
    monkeypatch.setattr(
        hardware_api,
        "native_sensor_capabilities",
        _sensor_report,
        raising=False,
    )

    api = hardware_api.HardwareAPI()

    result = api.dispatch("sensors")

    assert result["ok"] is True
    assert result["result"]["active_probe_required"] is True


def test_hardware_api_get_sensor_route(
    monkeypatch,
):
    monkeypatch.setattr(
        hardware_api,
        "native_sensor_capabilities",
        _sensor_report,
        raising=False,
    )

    api = hardware_api.HardwareAPI()
    server = hardware_api.serve_hardware_api(
        host="127.0.0.1",
        port=0,
        api=api,
    )

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )
    thread.start()

    try:
        host, port = server.server_address

        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/v1/hardware/sensors",
            timeout=5,
        ) as response:
            payload = json.loads(
                response.read().decode("utf-8")
            )

        assert response.status == 200
        assert payload["ok"] is True

        report = payload["result"]

        assert report["platform"]["termux"] is True
        assert (
            report["capabilities"]["camera_capture"]["verified"]
            is True
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
