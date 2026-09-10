from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import sophyane.hardware_api as hardware_api


def _verified_stt_result():
    return {
        "id": "speech_to_text",
        "command": "termux-speech-to-text",
        "command_path": "/mock/termux-speech-to-text",
        "command_present": True,
        "available": True,
        "verified": True,
        "backend": "termux_api",
        "reason": "verified_transcript",
        "transcript": "hello from sophyane",
        "transcript_verified": True,
        "transcript_chars": 19,
        "process_returncode": 0,
        "evidence_recorded": True,
        "evidence_observed_at":
            "2026-09-08T10:15:00+00:00",
    }


def test_stt_dispatch_is_explicit(
    monkeypatch,
):
    calls = []

    def fake_probe():
        calls.append(True)
        return _verified_stt_result()

    monkeypatch.setattr(
        hardware_api,
        "probe_and_record_speech_to_text",
        fake_probe,
        raising=False,
    )

    result = hardware_api.HardwareAPI().dispatch(
        "speech_to_text_probe"
    )

    assert result["ok"] is True
    assert calls == [True]

    probe = result["result"]

    assert probe["verified"] is True
    assert probe["transcript_verified"] is True
    assert probe["transcript"] == "hello from sophyane"


def test_sensor_status_does_not_activate_stt(
    monkeypatch,
):
    monkeypatch.setattr(
        hardware_api,
        "native_sensor_capabilities",
        lambda: {
            "ok": True,
            "capabilities": {
                "speech_to_text": {
                    "id": "speech_to_text",
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

    def forbidden():
        raise AssertionError(
            "read-only sensor status invoked STT"
        )

    monkeypatch.setattr(
        hardware_api,
        "probe_and_record_speech_to_text",
        forbidden,
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
            "speech_to_text"
        ][
            "reason"
        ]
        == "active_probe_required"
    )


def test_http_post_stt_probe_route(
    monkeypatch,
):
    calls = []

    def fake_probe():
        calls.append(True)
        return _verified_stt_result()

    monkeypatch.setattr(
        hardware_api,
        "probe_and_record_speech_to_text",
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

        request = urllib.request.Request(
            (
                f"http://127.0.0.1:{port}"
                "/v1/hardware/sensors/speech-to-text/probe"
            ),
            data=b"{}",
            headers={
                "Content-Type": "application/json",
            },
            method="POST",
        )

        with urllib.request.urlopen(
            request,
            timeout=5,
        ) as response:
            status = response.status
            payload = json.loads(
                response.read().decode("utf-8")
            )

        assert status == 200
        assert payload["ok"] is True
        assert calls == [True]
        assert (
            payload["result"]["transcript_verified"]
            is True
        )

    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http_get_stt_probe_route_is_not_active(
    monkeypatch,
):
    calls = []

    def forbidden():
        calls.append(True)
        raise AssertionError(
            "GET STT probe activated hardware"
        )

    monkeypatch.setattr(
        hardware_api,
        "probe_and_record_speech_to_text",
        forbidden,
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
                    "/v1/hardware/sensors/speech-to-text/probe"
                ),
                timeout=5,
            )
        except urllib.error.HTTPError as error:
            assert error.code == 404
        else:
            raise AssertionError(
                "GET STT active route unexpectedly succeeded"
            )

        assert calls == []

    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
