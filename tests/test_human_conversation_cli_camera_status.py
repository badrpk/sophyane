from __future__ import annotations

import builtins

import sophyane.human_conversation_cli as cli


def _report_without_probe():
    return {
        "ok": True,
        "capabilities": {
            "camera_capture": {
                "id": "camera_capture",
                "command": "termux-camera-photo",
                "command_present": True,
                "available": False,
                "verified": True,
                "backend": None,
                "reason":
                    "google_play_termux_api_unavailable",
            },
        },
    }


def _report_with_probe():
    return {
        "ok": True,
        "capabilities": {
            "camera_capture": {
                "id": "camera_capture",
                "command": "termux-camera-photo",
                "command_present": True,
                "available": False,
                "verified": True,
                "backend": None,
                "reason":
                    "google_play_termux_api_unavailable",
                "last_probe": {
                    "capability_id":
                        "camera_capture",
                    "available": True,
                    "verified": True,
                    "backend":
                        "android_camera_activity",
                    "reason":
                        "verified_capture",
                    "artifact_verified": True,
                    "image_verified": True,
                    "image_format": "JPEG",
                    "image_width": 4000,
                    "image_height": 2252,
                    "fresh": True,
                    "age_seconds": 12.5,
                    "current_platform_match": True,
                },
            },
        },
    }


def test_camera_status_without_probe_is_truthful(
    monkeypatch,
):
    monkeypatch.setattr(
        cli,
        "_camera_status_report",
        _report_without_probe,
        raising=False,
    )

    text = cli._camera_status_text()

    assert "termux-camera-photo" in text
    assert "available: no" in text.lower()

    assert (
        "google_play_termux_api_unavailable"
        in text
    )

    assert (
        "last active camera probe: none"
        in text.lower()
    )


def test_camera_status_reports_active_evidence_separately(
    monkeypatch,
):
    monkeypatch.setattr(
        cli,
        "_camera_status_report",
        _report_with_probe,
        raising=False,
    )

    text = cli._camera_status_text()

    # Base read-only discovery remains unavailable.
    assert "available: no" in text.lower()

    # Active evidence is displayed separately.
    assert "android_camera_activity" in text
    assert "verified_capture" in text
    assert "image verified: yes" in text.lower()
    assert "4000x2252" in text
    assert "fresh: yes" in text.lower()
    assert "platform match: yes" in text.lower()


def test_camera_status_report_uses_read_only_sensor_api(
    monkeypatch,
):
    calls = []

    class FakeHardwareAPI:
        def sensors(self):
            calls.append("sensors")
            return _report_without_probe()

        def camera_probe(self, *args, **kwargs):
            raise AssertionError(
                "/camera-status activated Camera"
            )

    monkeypatch.setattr(
        cli,
        "_camera_hardware_api_factory",
        lambda: FakeHardwareAPI(),
        raising=False,
    )

    result = cli._camera_status_report()

    assert result["ok"] is True
    assert calls == ["sensors"]


def test_camera_status_formatter_never_calls_active_probe(
    monkeypatch,
):
    monkeypatch.setattr(
        cli,
        "_camera_status_report",
        _report_without_probe,
        raising=False,
    )

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "camera status invoked active capture"
        )

    monkeypatch.setattr(
        cli,
        "probe_and_record_camera_capture",
        forbidden,
        raising=False,
    )

    text = cli._camera_status_text()

    assert "camera" in text.lower()


def test_camera_status_command_branch_is_present():
    from pathlib import Path

    source = Path(
        "src/sophyane/human_conversation_cli.py"
    ).read_text()

    assert '"/camera-status"' in source
