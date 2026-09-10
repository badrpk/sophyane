from __future__ import annotations

from datetime import datetime

import json

import sophyane.native_sensor_evidence as evidence


def _verified_microphone_result():
    return {
        "id": "microphone_capture",
        "command": "termux-microphone-record",
        "command_path": "/mock/termux-microphone-record",
        "command_present": True,
        "available": True,
        "verified": True,
        "backend": "termux_api",
        "reason": "verified_capture",
        "artifact_verified": True,
        "container_verified": True,
        "artifact_path": "/tmp/example.m4a",
        "artifact_bytes": 5861,
        "media_payload_bytes": 4972,
        "process_returncode": 0,
        "audio_verified": True,
        "audio_codec": "mp4a",
    }


def test_record_and_read_sensor_probe_evidence(
    tmp_path,
):
    path = tmp_path / "evidence.json"

    stored = evidence.record_sensor_probe_evidence(
        _verified_microphone_result(),
        path=path,
    )

    assert stored["capability_id"] == "microphone_capture"
    assert stored["available"] is True
    assert stored["verified"] is True
    assert stored["reason"] == "verified_capture"
    assert stored["audio_verified"] is True
    assert stored["audio_codec"] == "mp4a"
    assert stored["artifact_bytes"] == 5861
    assert stored["media_payload_bytes"] == 4972
    assert stored["observed_at"]

    loaded = evidence.read_sensor_probe_evidence(
        "microphone_capture",
        path=path,
    )

    assert loaded is not None
    assert loaded["capability_id"] == "microphone_capture"
    assert loaded["audio_verified"] is True
    assert loaded["audio_codec"] == "mp4a"


def test_evidence_store_does_not_persist_command_output(
    tmp_path,
):
    path = tmp_path / "evidence.json"

    result = _verified_microphone_result()
    result["output"] = "potentially large runtime output"

    evidence.record_sensor_probe_evidence(
        result,
        path=path,
    )

    raw = json.loads(
        path.read_text()
    )

    stored = raw["probes"]["microphone_capture"]

    assert "output" not in stored


def test_multiple_capabilities_do_not_overwrite_each_other(
    tmp_path,
):
    path = tmp_path / "evidence.json"

    evidence.record_sensor_probe_evidence(
        _verified_microphone_result(),
        path=path,
    )

    evidence.record_sensor_probe_evidence(
        {
            "id": "camera_capture",
            "available": False,
            "verified": True,
            "backend": None,
            "reason": "google_play_termux_api_unavailable",
            "artifact_verified": False,
            "container_verified": False,
            "artifact_bytes": 0,
            "media_payload_bytes": 0,
            "process_returncode": 0,
        },
        path=path,
    )

    microphone = evidence.read_sensor_probe_evidence(
        "microphone_capture",
        path=path,
    )

    camera = evidence.read_sensor_probe_evidence(
        "camera_capture",
        path=path,
    )

    assert microphone is not None
    assert microphone["available"] is True

    assert camera is not None
    assert camera["available"] is False
    assert (
        camera["reason"]
        == "google_play_termux_api_unavailable"
    )


def test_attach_evidence_preserves_discovery_truth(
    tmp_path,
):
    path = tmp_path / "evidence.json"

    evidence.record_sensor_probe_evidence(
        _verified_microphone_result(),
        path=path,
    )

    report = {
        "ok": True,
        "capabilities": {
            "microphone_capture": {
                "id": "microphone_capture",
                "command_present": True,
                "available": False,
                "verified": False,
                "backend": None,
                "reason": "active_probe_required",
            },
        },
        "active_probe_required": True,
    }

    enriched = evidence.attach_sensor_probe_evidence(
        report,
        path=path,
    )

    microphone = enriched[
        "capabilities"
    ][
        "microphone_capture"
    ]

    # Read-only discovery semantics remain unchanged.
    assert microphone["available"] is False
    assert microphone["verified"] is False
    assert microphone["reason"] == "active_probe_required"

    # Active evidence is reported separately.
    last_probe = microphone["last_probe"]

    assert last_probe["available"] is True
    assert last_probe["verified"] is True
    assert last_probe["audio_verified"] is True
    assert last_probe["audio_codec"] == "mp4a"


def test_attach_evidence_does_not_invoke_hardware(
    monkeypatch,
    tmp_path,
):
    path = tmp_path / "evidence.json"

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "read-only evidence attachment invoked hardware"
        )

    monkeypatch.setattr(
        evidence.subprocess,
        "run",
        forbidden,
        raising=False,
    )

    report = {
        "ok": True,
        "capabilities": {
            "microphone_capture": {
                "id": "microphone_capture",
                "available": False,
                "verified": False,
                "reason": "active_probe_required",
            },
        },
    }

    enriched = evidence.attach_sensor_probe_evidence(
        report,
        path=path,
    )

    assert (
        "last_probe"
        not in enriched["capabilities"]["microphone_capture"]
    )


def test_speech_transcript_content_is_not_persisted(
    tmp_path,
):
    path = tmp_path / "evidence.json"

    evidence.record_sensor_probe_evidence(
        {
            "id": "speech_to_text",
            "available": True,
            "verified": True,
            "backend": "termux_api",
            "reason": "verified_transcript",
            "transcript_verified": True,
            "transcript_chars": 24,
            "transcript": "Sophyane microphone test",
            "process_returncode": 0,
        },
        path=path,
    )

    raw = json.loads(
        path.read_text()
    )

    stored = raw[
        "probes"
    ][
        "speech_to_text"
    ]

    assert stored["transcript_verified"] is True
    assert stored["transcript_chars"] == 24
    assert "transcript" not in stored


def test_recorded_sensor_evidence_contains_platform_fingerprint(
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
            "termux_version": "googleplay.2026.06.21",
            "backend": "termux_api",
        },
        raising=False,
    )

    stored = evidence.record_sensor_probe_evidence(
        {
            "id": "speech_to_text",
            "available": True,
            "verified": True,
            "backend": "termux_api",
            "reason": "verified_transcript",
            "transcript_verified": True,
            "transcript_chars": 5,
        },
        path=path,
    )

    assert stored[
        "platform_fingerprint"
    ] == {
        "android_release": "16",
        "device_model": "SM-S928B",
        "termux_version": "googleplay.2026.06.21",
        "backend": "termux_api",
    }


def test_read_sensor_evidence_marks_recent_matching_probe_fresh(
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
            "termux_version": "googleplay.2026.06.21",
            "backend": "termux_api",
        },
        raising=False,
    )

    monkeypatch.setattr(
        evidence,
        "_utc_now",
        lambda: datetime.fromisoformat(
            "2026-09-08T10:20:30+00:00"
        ),
        raising=False,
    )

    path.write_text(
        json.dumps(
            {
                "version": 1,
                "probes": {
                    "speech_to_text": {
                        "capability_id": "speech_to_text",
                        "observed_at":
                            "2026-09-08T10:20:00+00:00",
                        "available": True,
                        "verified": True,
                        "backend": "termux_api",
                        "reason": "verified_transcript",
                        "transcript_verified": True,
                        "transcript_chars": 5,
                        "platform_fingerprint": {
                            "android_release": "16",
                            "device_model": "SM-S928B",
                            "termux_version":
                                "googleplay.2026.06.21",
                            "backend": "termux_api",
                        },
                    },
                },
            }
        )
    )

    cached = evidence.read_sensor_probe_evidence(
        "speech_to_text",
        path=path,
        freshness_ttl_seconds=300,
    )

    assert cached is not None

    assert cached["age_seconds"] == 30.0
    assert cached["freshness_ttl_seconds"] == 300
    assert cached["current_platform_match"] is True
    assert cached["fresh"] is True


def test_read_sensor_evidence_marks_old_probe_stale(
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
            "termux_version": "googleplay.2026.06.21",
            "backend": "termux_api",
        },
        raising=False,
    )

    monkeypatch.setattr(
        evidence,
        "_utc_now",
        lambda: datetime.fromisoformat(
            "2026-09-08T10:30:01+00:00"
        ),
        raising=False,
    )

    path.write_text(
        json.dumps(
            {
                "version": 1,
                "probes": {
                    "microphone_capture": {
                        "capability_id": "microphone_capture",
                        "observed_at":
                            "2026-09-08T10:20:00+00:00",
                        "available": True,
                        "verified": True,
                        "backend": "termux_api",
                        "reason": "verified_capture",
                        "audio_verified": True,
                        "platform_fingerprint": {
                            "android_release": "16",
                            "device_model": "SM-S928B",
                            "termux_version":
                                "googleplay.2026.06.21",
                            "backend": "termux_api",
                        },
                    },
                },
            }
        )
    )

    cached = evidence.read_sensor_probe_evidence(
        "microphone_capture",
        path=path,
        freshness_ttl_seconds=600,
    )

    assert cached is not None
    assert cached["age_seconds"] == 601.0
    assert cached["current_platform_match"] is True
    assert cached["fresh"] is False


def test_platform_mismatch_makes_cached_probe_not_fresh(
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
            "termux_version": "googleplay.NEW",
            "backend": "termux_api",
        },
        raising=False,
    )

    monkeypatch.setattr(
        evidence,
        "_utc_now",
        lambda: datetime.fromisoformat(
            "2026-09-08T10:20:10+00:00"
        ),
        raising=False,
    )

    path.write_text(
        json.dumps(
            {
                "version": 1,
                "probes": {
                    "speech_to_text": {
                        "capability_id": "speech_to_text",
                        "observed_at":
                            "2026-09-08T10:20:00+00:00",
                        "available": True,
                        "verified": True,
                        "backend": "termux_api",
                        "reason": "verified_transcript",
                        "transcript_verified": True,
                        "platform_fingerprint": {
                            "android_release": "16",
                            "device_model": "SM-S928B",
                            "termux_version":
                                "googleplay.OLD",
                            "backend": "termux_api",
                        },
                    },
                },
            }
        )
    )

    cached = evidence.read_sensor_probe_evidence(
        "speech_to_text",
        path=path,
        freshness_ttl_seconds=300,
    )

    assert cached is not None
    assert cached["age_seconds"] == 10.0
    assert cached["current_platform_match"] is False
    assert cached["fresh"] is False


def test_missing_or_legacy_platform_fingerprint_is_not_current_proof(
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
            "termux_version": "googleplay.2026.06.21",
            "backend": "termux_api",
        },
        raising=False,
    )

    monkeypatch.setattr(
        evidence,
        "_utc_now",
        lambda: datetime.fromisoformat(
            "2026-09-08T10:20:10+00:00"
        ),
        raising=False,
    )

    path.write_text(
        json.dumps(
            {
                "version": 1,
                "probes": {
                    "speech_to_text": {
                        "capability_id": "speech_to_text",
                        "observed_at":
                            "2026-09-08T10:20:00+00:00",
                        "available": True,
                        "verified": True,
                        "reason": "verified_transcript",
                    },
                },
            }
        )
    )

    cached = evidence.read_sensor_probe_evidence(
        "speech_to_text",
        path=path,
        freshness_ttl_seconds=300,
    )

    assert cached is not None
    assert cached["current_platform_match"] is False
    assert cached["fresh"] is False


def test_negative_age_is_clamped_to_zero(
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
            "termux_version": "googleplay.2026.06.21",
            "backend": "termux_api",
        },
        raising=False,
    )

    monkeypatch.setattr(
        evidence,
        "_utc_now",
        lambda: datetime.fromisoformat(
            "2026-09-08T10:19:59+00:00"
        ),
        raising=False,
    )

    path.write_text(
        json.dumps(
            {
                "version": 1,
                "probes": {
                    "speech_to_text": {
                        "capability_id": "speech_to_text",
                        "observed_at":
                            "2026-09-08T10:20:00+00:00",
                        "available": True,
                        "verified": True,
                        "platform_fingerprint": {
                            "android_release": "16",
                            "device_model": "SM-S928B",
                            "termux_version":
                                "googleplay.2026.06.21",
                            "backend": "termux_api",
                        },
                    },
                },
            }
        )
    )

    cached = evidence.read_sensor_probe_evidence(
        "speech_to_text",
        path=path,
        freshness_ttl_seconds=300,
    )

    assert cached is not None
    assert cached["age_seconds"] == 0.0
