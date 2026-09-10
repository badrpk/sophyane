from __future__ import annotations

import json

import sophyane.native_sensor_evidence as evidence


def _camera_result():
    return {
        "id": "camera_capture",
        "command": "am",
        "command_path": "/mock/am",
        "command_present": True,
        "available": True,
        "verified": True,
        "backend": "android_camera_activity",
        "reason": "verified_capture",
        "artifact_path": "/tmp/camera.jpg",
        "artifact_bytes": 8025184,
        "artifact_verified": True,
        "image_verified": True,
        "image_format": "JPEG",
        "image_width": 4000,
        "image_height": 2252,
        "artifact_sha256": "1" * 64,
        "jpeg_soi_verified": True,
        "jpeg_eoi_present": True,
        "pixel_decode_verified": True,
        "process_returncode": 0,
        "output": "large or sensitive runtime output",
    }


def test_camera_evidence_persists_only_metadata(
    monkeypatch,
    tmp_path,
):
    path = tmp_path / "evidence.json"

    monkeypatch.setattr(
        evidence,
        "_current_platform_fingerprint",
        lambda: {
            "android_release": "16",
            "device_model": "SM-S928B",
            "termux_version":
                "googleplay.2026.06.21",
            "backend": "termux_api",
        },
    )

    stored = (
        evidence.record_sensor_probe_evidence(
            _camera_result(),
            path=path,
        )
    )

    assert stored["capability_id"] == "camera_capture"
    assert stored["available"] is True
    assert stored["verified"] is True
    assert (
        stored["backend"]
        == "android_camera_activity"
    )
    assert stored["image_verified"] is True
    assert stored["image_format"] == "JPEG"
    assert stored["image_width"] == 4000
    assert stored["image_height"] == 2252
    assert (
        stored["artifact_sha256"]
        == "1" * 64
    )

    raw = json.loads(
        path.read_text()
    )

    item = raw[
        "probes"
    ][
        "camera_capture"
    ]

    assert "output" not in item
    assert "image_bytes" not in item
    assert "image_data" not in item


def test_camera_backend_fingerprint_remains_fresh_on_same_platform(
    monkeypatch,
    tmp_path,
):
    path = tmp_path / "evidence.json"

    fingerprint = {
        "android_release": "16",
        "device_model": "SM-S928B",
        "termux_version":
            "googleplay.2026.06.21",
        "backend": "termux_api",
    }

    monkeypatch.setattr(
        evidence,
        "_current_platform_fingerprint",
        lambda: dict(fingerprint),
    )

    evidence.record_sensor_probe_evidence(
        _camera_result(),
        path=path,
    )

    loaded = (
        evidence.read_sensor_probe_evidence(
            "camera_capture",
            path=path,
        )
    )

    assert loaded is not None
    assert (
        loaded["platform_fingerprint"]["backend"]
        == "android_camera_activity"
    )
    assert loaded["current_platform_match"] is True
    assert loaded["fresh"] is True
