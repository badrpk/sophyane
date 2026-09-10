from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import sophyane.hardware_api as hardware_api


def _verified_probe_result(
    duration_seconds: int = 3,
):
    return {
        "id": "microphone_capture",
        "available": True,
        "verified": True,
        "backend": "termux_api",
        "reason": "verified_capture",
        "artifact_verified": True,
        "container_verified": True,
        "audio_verified": True,
        "audio_codec": "mp4a",
        "audio_track_declared": True,
        "audio_codec_declared": True,
        "artifact_path": "/tmp/microphone-test.m4a",
        "artifact_bytes": 5886,
        "media_payload_bytes": 4997,
        "process_returncode": 0,
        "evidence_recorded": True,
        "evidence_observed_at":
            "2026-09-08T10:06:29+00:00",
        "requested_duration_seconds":
            duration_seconds,
    }


def test_microphone_probe_dispatch_is_explicit(
    monkeypatch,
):
    calls = []

    def fake_probe(
        *,
        duration_seconds=1,
    ):
        calls.append(
            duration_seconds
        )
        return _verified_probe_result(
            duration_seconds
        )

    monkeypatch.setattr(
        hardware_api,
        "probe_and_record_microphone_capture",
        fake_probe,
        raising=False,
    )

    result = hardware_api.HardwareAPI().dispatch(
        "microphone_probe",
        {
            "duration_seconds": 3,
        },
    )

    assert result["ok"] is True
    assert calls == [3]

    probe = result["result"]

    assert probe["available"] is True
    assert probe["verified"] is True
    assert probe["audio_verified"] is True
    assert probe["audio_codec"] == "mp4a"


def test_microphone_probe_default_duration_is_one_second(
    monkeypatch,
):
    calls = []

    def fake_probe(
        *,
        duration_seconds=1,
    ):
        calls.append(
            duration_seconds
        )
        return _verified_probe_result(
            duration_seconds
        )

    monkeypatch.setattr(
        hardware_api,
        "probe_and_record_microphone_capture",
        fake_probe,
        raising=False,
    )

    result = hardware_api.HardwareAPI().dispatch(
        "microphone_probe",
        {},
    )

    assert result["ok"] is True
    assert calls == [1]


def test_microphone_probe_rejects_invalid_duration_without_hardware(
    monkeypatch,
):
    calls = []

    def forbidden_probe(**kwargs):
        calls.append(
            kwargs
        )
        raise AssertionError(
            "invalid input reached microphone hardware"
        )

    monkeypatch.setattr(
        hardware_api,
        "probe_and_record_microphone_capture",
        forbidden_probe,
        raising=False,
    )

    invalid = (
        0,
        11,
        -1,
        True,
        1.5,
        "three",
        "",
        None,
    )

    for value in invalid:
        result = hardware_api.HardwareAPI().dispatch(
            "microphone_probe",
            {
                "duration_seconds": value,
            },
        )

        assert result["ok"] is False
        assert (
            result["error"]
            == "duration_seconds must be an integer from 1 to 10"
        )

    assert calls == []


def test_read_only_sensor_dispatch_never_invokes_microphone_probe(
    monkeypatch,
):
    monkeypatch.setattr(
        hardware_api,
        "native_sensor_capabilities",
        lambda: {
            "ok": True,
            "capabilities": {
                "microphone_capture": {
                    "id": "microphone_capture",
                    "available": False,
                    "verified": False,
                    "reason": "active_probe_required",
                },
            },
            "active_probe_required": True,
        },
    )

    monkeypatch.setattr(
        hardware_api,
        "attach_sensor_probe_evidence",
        lambda report: report,
    )

    def forbidden_probe(**kwargs):
        raise AssertionError(
            "GET/read-only sensor status activated microphone"
        )

    monkeypatch.setattr(
        hardware_api,
        "probe_and_record_microphone_capture",
        forbidden_probe,
        raising=False,
    )

    result = hardware_api.HardwareAPI().dispatch(
        "sensors"
    )

    assert result["ok"] is True
    assert (
        result[
            "result"
        ][
            "capabilities"
        ][
            "microphone_capture"
        ][
            "reason"
        ]
        == "active_probe_required"
    )


def test_http_post_microphone_probe_route(
    monkeypatch,
):
    calls = []

    def fake_probe(
        *,
        duration_seconds=1,
    ):
        calls.append(
            duration_seconds
        )
        return _verified_probe_result(
            duration_seconds
        )

    monkeypatch.setattr(
        hardware_api,
        "probe_and_record_microphone_capture",
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
                "duration_seconds": 4,
            }
        ).encode(
            "utf-8"
        )

        request = urllib.request.Request(
            (
                f"http://127.0.0.1:{port}"
                "/v1/hardware/sensors/microphone/probe"
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
        assert calls == [4]
        assert payload["result"]["audio_verified"] is True

    finally:
        server.shutdown()
        server.server_close()
        thread.join(
            timeout=5
        )


def test_http_get_probe_route_does_not_activate_hardware(
    monkeypatch,
):
    calls = []

    def forbidden_probe(**kwargs):
        calls.append(
            kwargs
        )
        raise AssertionError(
            "GET probe route activated hardware"
        )

    monkeypatch.setattr(
        hardware_api,
        "probe_and_record_microphone_capture",
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
                    "/v1/hardware/sensors/microphone/probe"
                ),
                timeout=5,
            )
        except urllib.error.HTTPError as error:
            status = error.code
            payload = json.loads(
                error.read().decode(
                    "utf-8"
                )
            )
        else:
            raise AssertionError(
                "GET active probe route unexpectedly succeeded"
            )

        assert status == 404
        assert payload["ok"] is False
        assert calls == []

    finally:
        server.shutdown()
        server.server_close()
        thread.join(
            timeout=5
        )


def test_http_invalid_probe_duration_does_not_activate_hardware(
    monkeypatch,
):
    calls = []

    def forbidden_probe(**kwargs):
        calls.append(
            kwargs
        )
        raise AssertionError(
            "invalid POST reached microphone hardware"
        )

    monkeypatch.setattr(
        hardware_api,
        "probe_and_record_microphone_capture",
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

        body = json.dumps(
            {
                "duration_seconds": 99,
            }
        ).encode(
            "utf-8"
        )

        request = urllib.request.Request(
            (
                f"http://127.0.0.1:{port}"
                "/v1/hardware/sensors/microphone/probe"
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
        assert payload["ok"] is False
        assert (
            payload["error"]
            == "duration_seconds must be an integer from 1 to 10"
        )

        assert calls == []

    finally:
        server.shutdown()
        server.server_close()
        thread.join(
            timeout=5
        )
