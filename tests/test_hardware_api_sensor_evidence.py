from __future__ import annotations

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


def test_hardware_api_sensor_status_attaches_last_probe(
    monkeypatch,
):
    monkeypatch.setattr(
        hardware_api,
        "native_sensor_capabilities",
        _sensor_report,
    )

    def attach(report):
        report = dict(report)
        report["capabilities"] = {
            key: dict(value)
            for key, value
            in report["capabilities"].items()
        }

        report[
            "capabilities"
        ][
            "microphone_capture"
        ][
            "last_probe"
        ] = {
            "capability_id": "microphone_capture",
            "available": True,
            "verified": True,
            "reason": "verified_capture",
            "audio_verified": True,
            "audio_codec": "mp4a",
        }

        return report

    monkeypatch.setattr(
        hardware_api,
        "attach_sensor_probe_evidence",
        attach,
        raising=False,
    )

    result = hardware_api.HardwareAPI().sensors()

    microphone = result[
        "capabilities"
    ][
        "microphone_capture"
    ]

    assert microphone["available"] is False
    assert microphone["verified"] is False
    assert microphone["reason"] == "active_probe_required"

    assert microphone["last_probe"]["available"] is True
    assert microphone["last_probe"]["verified"] is True
    assert microphone["last_probe"]["audio_verified"] is True


def test_hardware_sensor_status_exposes_freshness_without_promoting_discovery(
    monkeypatch,
):
    monkeypatch.setattr(
        hardware_api,
        "native_sensor_capabilities",
        _sensor_report,
    )

    def attach(report):
        copied = dict(report)
        copied["capabilities"] = {
            key: dict(value)
            for key, value
            in report["capabilities"].items()
        }

        copied[
            "capabilities"
        ][
            "microphone_capture"
        ][
            "last_probe"
        ] = {
            "available": True,
            "verified": True,
            "reason": "verified_capture",
            "fresh": True,
            "age_seconds": 20.0,
            "freshness_ttl_seconds": 300,
            "current_platform_match": True,
        }

        return copied

    monkeypatch.setattr(
        hardware_api,
        "attach_sensor_probe_evidence",
        attach,
    )

    result = hardware_api.HardwareAPI().dispatch(
        "sensors"
    )

    assert result["ok"] is True

    microphone = result[
        "result"
    ][
        "capabilities"
    ][
        "microphone_capture"
    ]

    assert microphone["available"] is False
    assert microphone["verified"] is False
    assert microphone["reason"] == "active_probe_required"

    assert microphone["last_probe"]["fresh"] is True
    assert (
        microphone[
            "last_probe"
        ][
            "current_platform_match"
        ]
        is True
    )
