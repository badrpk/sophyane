from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import sophyane.hardware_api as hardware_api


def _verified_camera_result(
    wait_seconds: int = 60,
):
    return {
        "id": "camera_capture",
        "command": "am",
        "command_path": "/mock/am",
        "command_present": True,
        "available": True,
        "verified": True,
        "backend":
            "android_camera_activity",
        "reason":
            "verified_capture",
        "artifact_path":
            "/storage/emulated/0/DCIM/Camera/test.jpg",
        "artifact_bytes": 8084465,
        "artifact_verified": True,
        "image_verified": True,
        "image_format": "JPEG",
        "image_width": 4000,
        "image_height": 2252,
        "jpeg_soi_verified": True,
        "jpeg_eoi_present": True,
        "pixel_decode_verified": True,
        "artifact_sha256":
            "a" * 64,
        "process_returncode": 0,
        "evidence_recorded": True,
        "evidence_observed_at":
            "2026-09-08T11:33:26+00:00",
        "requested_wait_seconds":
            wait_seconds,
    }


def test_camera_probe_dispatch_is_explicit(
    monkeypatch,
):
    calls = []

    def fake_probe(
        *,
        wait_seconds=60,
    ):
        calls.append(
            wait_seconds
        )

        return _verified_camera_result(
            wait_seconds
        )

    monkeypatch.setattr(
        hardware_api,
        "probe_and_record_camera_capture",
        fake_probe,
        raising=False,
    )

    result = hardware_api.HardwareAPI().dispatch(
        "camera_probe",
        {
            "wait_seconds": 45,
        },
    )

    assert result["ok"] is True
    assert calls == [45]

    probe = result["result"]

    assert probe["available"] is True
    assert probe["verified"] is True
    assert probe["image_verified"] is True
    assert probe["image_format"] == "JPEG"
    assert (
        probe["backend"]
        == "android_camera_activity"
    )


def test_camera_probe_default_wait_is_sixty_seconds(
    monkeypatch,
):
    calls = []

    def fake_probe(
        *,
        wait_seconds=60,
    ):
        calls.append(
            wait_seconds
        )

        return _verified_camera_result(
            wait_seconds
        )

    monkeypatch.setattr(
        hardware_api,
        "probe_and_record_camera_capture",
        fake_probe,
        raising=False,
    )

    result = hardware_api.HardwareAPI().dispatch(
        "camera_probe",
        {},
    )

    assert result["ok"] is True
    assert calls == [60]


def test_camera_probe_rejects_invalid_wait_without_hardware(
    monkeypatch,
):
    calls = []

    def forbidden_probe(**kwargs):
        calls.append(
            kwargs
        )

        raise AssertionError(
            "invalid input reached camera hardware"
        )

    monkeypatch.setattr(
        hardware_api,
        "probe_and_record_camera_capture",
        forbidden_probe,
        raising=False,
    )

    invalid = (
        -1,
        0,
        121,
        True,
        1.5,
        "60",
        "",
        None,
    )

    for value in invalid:
        result = hardware_api.HardwareAPI().dispatch(
            "camera_probe",
            {
                "wait_seconds": value,
            },
        )

        assert result["ok"] is False

        assert (
            result["error"]
            == "wait_seconds must be an integer from 1 to 120"
        )

    assert calls == []


def test_read_only_sensor_dispatch_never_invokes_camera(
    monkeypatch,
):
    monkeypatch.setattr(
        hardware_api,
        "native_sensor_capabilities",
        lambda: {
            "ok": True,
            "capabilities": {
                "camera_capture": {
                    "id":
                        "camera_capture",
                    "command":
                        "termux-camera-photo",
                    "available":
                        False,
                    "verified":
                        True,
                    "reason":
                        "google_play_termux_api_unavailable",
                },
            },
            "active_probe_required": False,
        },
    )

    monkeypatch.setattr(
        hardware_api,
        "attach_sensor_probe_evidence",
        lambda report: report,
    )

    def forbidden_probe(**kwargs):
        raise AssertionError(
            "read-only status activated Camera"
        )

    monkeypatch.setattr(
        hardware_api,
        "probe_and_record_camera_capture",
        forbidden_probe,
        raising=False,
    )

    result = hardware_api.HardwareAPI().dispatch(
        "sensors"
    )

    assert result["ok"] is True

    camera = result[
        "result"
    ][
        "capabilities"
    ][
        "camera_capture"
    ]

    assert camera["available"] is False
    assert (
        camera["reason"]
        == "google_play_termux_api_unavailable"
    )


def test_http_post_camera_probe_route(
    monkeypatch,
):
    calls = []

    def fake_probe(
        *,
        wait_seconds=60,
    ):
        calls.append(
            wait_seconds
        )

        return _verified_camera_result(
            wait_seconds
        )

    monkeypatch.setattr(
        hardware_api,
        "probe_and_record_camera_capture",
        fake_probe,
        raising=False,
    )

    server = hardware_api.serve_hardware_api(
        host="127.0.0.1",
        port=0,
        api=hardware_api.HardwareAPI(),
    )

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )

    thread.start()

    try:
        _, port = server.server_address

        body = json.dumps(
            {
                "wait_seconds": 75,
            }
        ).encode(
            "utf-8"
        )

        request = urllib.request.Request(
            (
                f"http://127.0.0.1:{port}"
                "/v1/hardware/sensors/camera/probe"
            ),
            data=body,
            headers={
                "Content-Type":
                    "application/json",
            },
            method="POST",
        )

        with urllib.request.urlopen(
            request,
            timeout=5,
        ) as response:
            status = response.status

            payload = json.loads(
                response.read().decode(
                    "utf-8"
                )
            )

        assert status == 200
        assert payload["ok"] is True
        assert calls == [75]

        assert (
            payload[
                "result"
            ][
                "image_verified"
            ]
            is True
        )

    finally:
        server.shutdown()
        server.server_close()

        thread.join(
            timeout=5
        )


def test_http_get_camera_probe_route_never_activates_camera(
    monkeypatch,
):
    calls = []

    def forbidden_probe(**kwargs):
        calls.append(
            kwargs
        )

        raise AssertionError(
            "GET camera probe activated hardware"
        )

    monkeypatch.setattr(
        hardware_api,
        "probe_and_record_camera_capture",
        forbidden_probe,
        raising=False,
    )

    server = hardware_api.serve_hardware_api(
        host="127.0.0.1",
        port=0,
        api=hardware_api.HardwareAPI(),
    )

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )

    thread.start()

    try:
        _, port = server.server_address

        try:
            urllib.request.urlopen(
                (
                    f"http://127.0.0.1:{port}"
                    "/v1/hardware/sensors/camera/probe"
                ),
                timeout=5,
            )

        except urllib.error.HTTPError as error:
            assert error.code == 404

        else:
            raise AssertionError(
                "GET camera probe route unexpectedly succeeded"
            )

        assert calls == []

    finally:
        server.shutdown()
        server.server_close()

        thread.join(
            timeout=5
        )
