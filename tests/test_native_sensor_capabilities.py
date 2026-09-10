from __future__ import annotations

import sophyane.native_readonly_capabilities as native


def _commands():
    return {
        "termux-camera-photo":
            "/data/data/com.termux/files/usr/bin/termux-camera-photo",
        "termux-microphone-record":
            "/data/data/com.termux/files/usr/bin/termux-microphone-record",
        "termux-sensor":
            "/data/data/com.termux/files/usr/bin/termux-sensor",
        "termux-speech-to-text":
            "/data/data/com.termux/files/usr/bin/termux-speech-to-text",
    }


def test_google_play_camera_block_is_not_generalized_to_other_sensors(
    monkeypatch,
):
    monkeypatch.setenv(
        "TERMUX_VERSION",
        "googleplay.2026.06.21",
    )

    commands = _commands()

    monkeypatch.setattr(
        native.shutil,
        "which",
        lambda name: commands.get(name),
    )

    report = native.native_sensor_capabilities()

    assert report["platform"]["termux"] is True
    assert report["platform"]["google_play_termux"] is True

    camera = report["capabilities"]["camera_capture"]

    assert camera["command_present"] is True
    assert camera["available"] is False
    assert camera["verified"] is True
    assert camera["backend"] is None
    assert (
        camera["reason"]
        == "google_play_termux_api_unavailable"
    )

    # Real-device evidence only proves the camera backend failure.
    # Presence of the other wrappers is insufficient to classify their
    # runtime state without an explicit active probe.
    for capability_id in (
        "microphone_capture",
        "device_sensors",
        "speech_to_text",
    ):
        capability = report["capabilities"][capability_id]

        assert capability["command_present"] is True
        assert capability["available"] is False
        assert capability["verified"] is False
        assert capability["backend"] is None
        assert capability["reason"] == "active_probe_required"

    assert report["active_probe_required"] is True


def test_command_presence_alone_never_proves_sensor_availability(
    monkeypatch,
):
    monkeypatch.setenv(
        "TERMUX_VERSION",
        "0.118.3",
    )

    monkeypatch.setattr(
        native.shutil,
        "which",
        lambda name: (
            f"/mock/{name}"
            if name.startswith("termux-")
            else None
        ),
    )

    report = native.native_sensor_capabilities()

    for capability in report["capabilities"].values():
        assert capability["command_present"] is True
        assert capability["available"] is False
        assert capability["verified"] is False
        assert capability["reason"] == "active_probe_required"


def test_missing_sensor_command_is_deterministically_unavailable(
    monkeypatch,
):
    monkeypatch.delenv(
        "TERMUX_VERSION",
        raising=False,
    )

    monkeypatch.setattr(
        native.shutil,
        "which",
        lambda name: None,
    )

    report = native.native_sensor_capabilities()

    for capability in report["capabilities"].values():
        assert capability["command_present"] is False
        assert capability["available"] is False
        assert capability["verified"] is True
        assert capability["backend"] is None
        assert capability["reason"] == "command_not_found"


def test_native_sensor_probe_has_no_subprocess_side_effects(
    monkeypatch,
):
    monkeypatch.setenv(
        "TERMUX_VERSION",
        "googleplay.2026.06.21",
    )

    monkeypatch.setattr(
        native.shutil,
        "which",
        lambda name: f"/mock/{name}",
    )

    def forbidden_run(*args, **kwargs):
        raise AssertionError(
            "capability discovery must not invoke sensor commands"
        )

    monkeypatch.setattr(
        native.subprocess,
        "run",
        forbidden_run,
    )

    report = native.native_sensor_capabilities()

    assert report["ok"] is True


def test_native_sensor_report_is_explicit_about_verification_boundary(
    monkeypatch,
):
    monkeypatch.setenv(
        "TERMUX_VERSION",
        "non-google-play",
    )

    monkeypatch.setattr(
        native.shutil,
        "which",
        lambda name: f"/mock/{name}",
    )

    report = native.native_sensor_capabilities()

    assert (
        report["verification_policy"]
        == "command_presence_is_not_runtime_sensor_evidence"
    )
    assert report["active_probe_required"] is True
