from __future__ import annotations

import subprocess

from pathlib import Path
from types import SimpleNamespace

import sophyane.native_sensor_actions as actions


def _completed(
    *,
    returncode=0,
    stdout="",
    stderr="",
):
    return SimpleNamespace(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _box(kind: bytes, payload: bytes) -> bytes:
    return (
        (8 + len(payload)).to_bytes(4, "big")
        + kind
        + payload
    )


def _valid_m4a_bytes() -> bytes:
    return b"".join(
        (
            _box(
                b"ftyp",
                b"mp42\x00\x00\x00\x00isommp42",
            ),
            _box(
                b"mdat",
                b"\x01\x40\x22\x80"
                + b"x" * 256,
            ),
            _box(
                b"moov",
                b"\x00" * 64,
            ),
        )
    )


def test_microphone_permission_denied_is_not_available(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        actions.shutil,
        "which",
        lambda name: (
            "/mock/termux-microphone-record"
            if name == "termux-microphone-record"
            else None
        ),
    )

    monkeypatch.setattr(
        actions.subprocess,
        "run",
        lambda *args, **kwargs: _completed(
            returncode=0,
            stdout=(
                '{"error":"Please grant '
                'android.permission.RECORD_AUDIO"}'
            ),
        ),
    )

    monkeypatch.setattr(
        actions.time,
        "sleep",
        lambda seconds: (_ for _ in ()).throw(
            AssertionError(
                "permission failure must not wait"
            )
        ),
    )

    result = actions.probe_microphone_capture(
        output_dir=tmp_path,
        duration_seconds=1,
    )

    assert result["available"] is False
    assert result["verified"] is True
    assert result["artifact_verified"] is False
    assert result["container_verified"] is False
    assert result["reason"] == "permission_denied"
    assert result["backend"] == "termux_api"


def test_google_play_api_error_is_classified_without_wait(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        actions.shutil,
        "which",
        lambda name: (
            "/mock/termux-microphone-record"
            if name == "termux-microphone-record"
            else None
        ),
    )

    monkeypatch.setattr(
        actions.subprocess,
        "run",
        lambda *args, **kwargs: _completed(
            returncode=0,
            stdout=(
                "Termux:API is not yet available on Google Play"
            ),
        ),
    )

    monkeypatch.setattr(
        actions.time,
        "sleep",
        lambda seconds: (_ for _ in ()).throw(
            AssertionError(
                "API failure must not wait"
            )
        ),
    )

    result = actions.probe_microphone_capture(
        output_dir=tmp_path,
        duration_seconds=1,
    )

    assert result["available"] is False
    assert result["verified"] is True
    assert result["container_verified"] is False
    assert (
        result["reason"]
        == "google_play_termux_api_unavailable"
    )


def test_microphone_waits_before_quit_and_verifies_container(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        actions.shutil,
        "which",
        lambda name: (
            "/mock/termux-microphone-record"
            if name == "termux-microphone-record"
            else None
        ),
    )

    events = []

    def fake_sleep(seconds):
        events.append(
            ("sleep", seconds)
        )

    def fake_run(command, **kwargs):
        if "-f" in command:
            events.append(
                ("start", tuple(command))
            )

            path = Path(
                command[
                    command.index("-f") + 1
                ]
            )

            path.write_bytes(
                _valid_audio_m4a_bytes()
            )

            return _completed(
                returncode=0,
                stdout=(
                    "Recording started: "
                    + str(path)
                    + "\nMax Duration: 00:01"
                ),
            )

        if "-q" in command:
            events.append(
                ("quit", tuple(command))
            )

            return _completed(
                returncode=0,
                stdout="Recording finished",
            )

        raise AssertionError(command)

    monkeypatch.setattr(
        actions.time,
        "sleep",
        fake_sleep,
    )

    monkeypatch.setattr(
        actions.subprocess,
        "run",
        fake_run,
    )

    result = actions.probe_microphone_capture(
        output_dir=tmp_path,
        duration_seconds=1,
    )

    event_names = [
        event[0]
        for event in events
    ]

    assert event_names == [
        "start",
        "sleep",
        "quit",
    ]

    assert result["available"] is True
    assert result["verified"] is True
    assert result["artifact_verified"] is True
    assert result["container_verified"] is True
    assert result["media_payload_bytes"] > 0
    assert result["artifact_bytes"] > 0
    assert result["reason"] == "verified_capture"
    assert result["backend"] == "termux_api"


def test_nonempty_but_incomplete_mp4_is_not_verified(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        actions.shutil,
        "which",
        lambda name: (
            "/mock/termux-microphone-record"
            if name == "termux-microphone-record"
            else None
        ),
    )

    monkeypatch.setattr(
        actions.time,
        "sleep",
        lambda seconds: None,
    )

    def fake_run(command, **kwargs):
        if "-f" in command:
            path = Path(
                command[
                    command.index("-f") + 1
                ]
            )

            # ftyp + mdat, but deliberately no moov.
            path.write_bytes(
                _box(
                    b"ftyp",
                    b"mp42isom",
                )
                + _box(
                    b"mdat",
                    b"x" * 64,
                )
            )

            return _completed(
                returncode=0,
                stdout="Recording started",
            )

        return _completed(
            returncode=0,
            stdout="Recording finished",
        )

    monkeypatch.setattr(
        actions.subprocess,
        "run",
        fake_run,
    )

    result = actions.probe_microphone_capture(
        output_dir=tmp_path,
        duration_seconds=1,
    )

    assert result["available"] is False
    assert result["artifact_verified"] is False
    assert result["container_verified"] is False
    assert result["reason"] == "capture_artifact_invalid"


def test_zero_exit_without_artifact_is_not_success(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        actions.shutil,
        "which",
        lambda name: (
            "/mock/termux-microphone-record"
            if name == "termux-microphone-record"
            else None
        ),
    )

    monkeypatch.setattr(
        actions.time,
        "sleep",
        lambda seconds: None,
    )

    monkeypatch.setattr(
        actions.subprocess,
        "run",
        lambda *args, **kwargs: _completed(
            returncode=0,
            stdout="Recording started",
        ),
    )

    result = actions.probe_microphone_capture(
        output_dir=tmp_path,
        duration_seconds=1,
    )

    assert result["available"] is False
    assert result["artifact_verified"] is False
    assert result["container_verified"] is False
    assert result["reason"] == "capture_artifact_missing"


def test_missing_command_is_verified_unavailable(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        actions.shutil,
        "which",
        lambda name: None,
    )

    result = actions.probe_microphone_capture(
        output_dir=tmp_path,
        duration_seconds=1,
    )

    assert result["command_present"] is False
    assert result["available"] is False
    assert result["verified"] is True
    assert result["artifact_verified"] is False
    assert result["container_verified"] is False
    assert result["reason"] == "command_not_found"


def test_mp4_validator_rejects_arbitrary_nonempty_file(
    tmp_path,
):
    path = tmp_path / "fake.m4a"

    path.write_bytes(
        b"not actually an mp4 file"
    )

    evidence = actions.inspect_m4a_artifact(
        path
    )

    assert evidence["container_verified"] is False
    assert evidence["media_payload_bytes"] == 0


def test_mp4_validator_accepts_required_boxes(
    tmp_path,
):
    path = tmp_path / "real.m4a"

    path.write_bytes(
        _valid_m4a_bytes()
    )

    evidence = actions.inspect_m4a_artifact(
        path
    )

    assert evidence["container_verified"] is True
    assert evidence["has_ftyp"] is True
    assert evidence["has_mdat"] is True
    assert evidence["has_moov"] is True
    assert evidence["media_payload_bytes"] > 0


def _audio_moov_payload() -> bytes:
    hdlr_payload = (
        b"\x00\x00\x00\x00"  # version + flags
        + b"\x00\x00\x00\x00"  # pre_defined
        + b"soun"
        + b"\x00" * 12
        + b"SoundHandler\x00"
    )

    hdlr = _box(
        b"hdlr",
        hdlr_payload,
    )

    mp4a_entry = (
        (36).to_bytes(4, "big")
        + b"mp4a"
        + b"\x00" * 28
    )

    stsd_payload = (
        b"\x00\x00\x00\x00"  # version + flags
        + (1).to_bytes(4, "big")
        + mp4a_entry
    )

    stsd = _box(
        b"stsd",
        stsd_payload,
    )

    stbl = _box(
        b"stbl",
        stsd,
    )

    minf = _box(
        b"minf",
        stbl,
    )

    mdia = _box(
        b"mdia",
        hdlr + minf,
    )

    trak = _box(
        b"trak",
        mdia,
    )

    return trak


def _valid_audio_m4a_bytes() -> bytes:
    return b"".join(
        (
            _box(
                b"ftyp",
                b"mp42\x00\x00\x00\x00isommp42",
            ),
            _box(
                b"mdat",
                b"\x01\x40\x22\x80"
                + b"x" * 256,
            ),
            _box(
                b"moov",
                _audio_moov_payload(),
            ),
        )
    )


def test_mp4_validator_requires_declared_audio_track(
    tmp_path,
):
    path = tmp_path / "video-or-generic.mp4"

    path.write_bytes(
        _valid_m4a_bytes()
    )

    evidence = actions.inspect_m4a_artifact(
        path
    )

    assert evidence["container_verified"] is True
    assert evidence["audio_track_declared"] is False
    assert evidence["audio_codec_declared"] is False
    assert evidence["audio_verified"] is False


def test_mp4_validator_accepts_declared_mp4a_audio(
    tmp_path,
):
    path = tmp_path / "audio.m4a"

    path.write_bytes(
        _valid_audio_m4a_bytes()
    )

    evidence = actions.inspect_m4a_artifact(
        path
    )

    assert evidence["container_verified"] is True
    assert evidence["audio_track_declared"] is True
    assert evidence["audio_codec_declared"] is True
    assert evidence["audio_codec"] == "mp4a"
    assert evidence["audio_verified"] is True


def test_verified_microphone_result_exposes_audio_evidence(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        actions.shutil,
        "which",
        lambda name: (
            "/mock/termux-microphone-record"
            if name == "termux-microphone-record"
            else None
        ),
    )

    monkeypatch.setattr(
        actions.time,
        "sleep",
        lambda seconds: None,
    )

    def fake_run(command, **kwargs):
        if "-f" in command:
            path = Path(
                command[
                    command.index("-f") + 1
                ]
            )

            path.write_bytes(
                _valid_audio_m4a_bytes()
            )

            return _completed(
                returncode=0,
                stdout="Recording started",
            )

        return _completed(
            returncode=0,
            stdout="Recording finished",
        )

    monkeypatch.setattr(
        actions.subprocess,
        "run",
        fake_run,
    )

    result = actions.probe_microphone_capture(
        output_dir=tmp_path,
        duration_seconds=1,
    )

    assert result["available"] is True
    assert result["verified"] is True
    assert result["audio_verified"] is True
    assert result["audio_codec"] == "mp4a"
    assert result["audio_track_declared"] is True
    assert result["audio_codec_declared"] is True


def test_speech_to_text_probe_verifies_real_transcript(
    monkeypatch,
):
    monkeypatch.setattr(
        actions.shutil,
        "which",
        lambda name: (
            "/mock/termux-speech-to-text"
            if name == "termux-speech-to-text"
            else None
        ),
    )

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="Sophyane microphone test\n",
            stderr="",
        )

    monkeypatch.setattr(
        actions.subprocess,
        "run",
        fake_run,
    )

    result = actions.probe_speech_to_text()

    assert result["id"] == "speech_to_text"
    assert result["available"] is True
    assert result["verified"] is True
    assert result["reason"] == "verified_transcript"
    assert result["transcript_verified"] is True
    assert result["transcript"] == "Sophyane microphone test"
    assert result["transcript_chars"] == 24


def test_speech_to_text_probe_rejects_permission_error_as_transcript(
    monkeypatch,
):
    monkeypatch.setattr(
        actions.shutil,
        "which",
        lambda name: "/mock/termux-speech-to-text",
    )

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="",
            stderr=(
                "Please grant android.permission.RECORD_AUDIO"
            ),
        )

    monkeypatch.setattr(
        actions.subprocess,
        "run",
        fake_run,
    )

    result = actions.probe_speech_to_text()

    assert result["available"] is False
    assert result["verified"] is True
    assert result["reason"] == "permission_denied"
    assert result["transcript_verified"] is False
    assert result["transcript"] == ""


def test_speech_to_text_probe_rejects_google_play_api_error(
    monkeypatch,
):
    monkeypatch.setattr(
        actions.shutil,
        "which",
        lambda name: "/mock/termux-speech-to-text",
    )

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=(
                "Termux:API is not yet available on Google Play"
            ),
            stderr="",
        )

    monkeypatch.setattr(
        actions.subprocess,
        "run",
        fake_run,
    )

    result = actions.probe_speech_to_text()

    assert result["available"] is False
    assert result["verified"] is True
    assert (
        result["reason"]
        == "google_play_termux_api_unavailable"
    )
    assert result["transcript_verified"] is False


def test_speech_to_text_probe_timeout_is_not_verified(
    monkeypatch,
):
    monkeypatch.setattr(
        actions.shutil,
        "which",
        lambda name: "/mock/termux-speech-to-text",
    )

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=args[0],
            timeout=20,
        )

    monkeypatch.setattr(
        actions.subprocess,
        "run",
        fake_run,
    )

    result = actions.probe_speech_to_text()

    assert result["available"] is False
    assert result["verified"] is False
    assert result["reason"] == "probe_timeout"
    assert result["transcript_verified"] is False


def test_speech_to_text_probe_requires_nonempty_transcript(
    monkeypatch,
):
    monkeypatch.setattr(
        actions.shutil,
        "which",
        lambda name: "/mock/termux-speech-to-text",
    )

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="\n",
            stderr="",
        )

    monkeypatch.setattr(
        actions.subprocess,
        "run",
        fake_run,
    )

    result = actions.probe_speech_to_text()

    assert result["available"] is False
    assert result["verified"] is True
    assert result["reason"] == "no_transcript_observed"
    assert result["transcript_verified"] is False


def test_speech_to_text_no_match_is_not_verified_transcript(
    monkeypatch,
):
    monkeypatch.setattr(
        actions.shutil,
        "which",
        lambda name: "/mock/termux-speech-to-text",
    )

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="ERROR: ERROR_NO_MATCH\n",
            stderr="",
        )

    monkeypatch.setattr(
        actions.subprocess,
        "run",
        fake_run,
    )

    result = actions.probe_speech_to_text()

    assert result["available"] is True
    assert result["verified"] is True
    assert result["reason"] == "recognizer_no_match"

    assert result["transcript"] == ""
    assert result["transcript_chars"] == 0
    assert result["transcript_verified"] is False


def test_speech_to_text_recognizer_error_is_not_transcript(
    monkeypatch,
):
    monkeypatch.setattr(
        actions.shutil,
        "which",
        lambda name: "/mock/termux-speech-to-text",
    )

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="ERROR: ERROR_NETWORK\n",
            stderr="",
        )

    monkeypatch.setattr(
        actions.subprocess,
        "run",
        fake_run,
    )

    result = actions.probe_speech_to_text()

    assert result["available"] is False
    assert result["verified"] is True
    assert result["reason"] == "recognizer_error"

    assert result["transcript"] == ""
    assert result["transcript_chars"] == 0
    assert result["transcript_verified"] is False


def test_speech_to_text_error_marker_must_not_hide_real_transcript(
    monkeypatch,
):
    monkeypatch.setattr(
        actions.shutil,
        "which",
        lambda name: "/mock/termux-speech-to-text",
    )

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="this is a real spoken sentence\n",
            stderr="",
        )

    monkeypatch.setattr(
        actions.subprocess,
        "run",
        fake_run,
    )

    result = actions.probe_speech_to_text()

    assert result["available"] is True
    assert result["verified"] is True
    assert result["reason"] == "verified_transcript"
    assert result["transcript_verified"] is True
    assert (
        result["transcript"]
        == "this is a real spoken sentence"
    )
