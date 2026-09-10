from __future__ import annotations

import sophyane.human_conversation_cli as cli


def _probe(
    monkeypatch,
    capsys,
    result,
):
    calls = []

    def fake_probe():
        calls.append(True)
        return dict(result)

    monkeypatch.setattr(
        cli,
        "probe_and_record_speech_to_text",
        fake_probe,
    )

    text = cli._voice_input_text()

    output = capsys.readouterr().out

    return {
        "text": text,
        "output": output,
        "calls": calls,
    }


def test_voice_prints_listening_before_verified_transcript(
    monkeypatch,
    capsys,
):
    result = _probe(
        monkeypatch,
        capsys,
        {
            "available": True,
            "verified": True,
            "reason":
                "verified_transcript",
            "transcript":
                "hello sophyane",
            "transcript_verified":
                True,
            "output":
                "RAW_BACKEND_OUTPUT",
        },
    )

    assert len(result["calls"]) == 1

    assert (
        "Listening..."
        in result["output"]
    )

    assert (
        "You (voice): hello sophyane"
        in result["output"]
    )

    assert (
        result["output"].index(
            "Listening..."
        )
        <
        result["output"].index(
            "You (voice):"
        )
    )

    assert (
        result["text"]
        == "hello sophyane"
    )

    assert (
        "RAW_BACKEND_OUTPUT"
        not in result["output"]
    )


def test_no_match_is_clear_and_hides_backend_output(
    monkeypatch,
    capsys,
):
    result = _probe(
        monkeypatch,
        capsys,
        {
            "available": True,
            "verified": True,
            "reason":
                "recognizer_no_match",
            "transcript": "",
            "transcript_verified":
                False,
            "output":
                "ERROR: ERROR_NO_MATCH",
        },
    )

    assert result["text"] is None

    assert (
        "Listening..."
        in result["output"]
    )

    assert (
        "No speech was recognized."
        in result["output"]
    )

    assert (
        "ERROR_NO_MATCH"
        not in result["output"]
    )


def test_permission_error_hides_raw_backend_output(
    monkeypatch,
    capsys,
):
    result = _probe(
        monkeypatch,
        capsys,
        {
            "available": False,
            "verified": True,
            "reason":
                "permission_denied",
            "transcript": "",
            "transcript_verified":
                False,
            "output":
                "android.permission.RECORD_AUDIO denied",
        },
    )

    assert result["text"] is None

    assert (
        "Microphone permission is not available."
        in result["output"]
    )

    assert (
        "android.permission.RECORD_AUDIO"
        not in result["output"]
    )


def test_recognizer_error_hides_raw_backend_output(
    monkeypatch,
    capsys,
):
    result = _probe(
        monkeypatch,
        capsys,
        {
            "available": False,
            "verified": True,
            "reason":
                "recognizer_error",
            "transcript": "",
            "transcript_verified":
                False,
            "output":
                "ERROR: ERROR_NETWORK",
        },
    )

    assert result["text"] is None

    assert (
        "Speech recognizer returned an error."
        in result["output"]
    )

    assert (
        "ERROR_NETWORK"
        not in result["output"]
    )


def test_timeout_message_is_local_and_clear(
    monkeypatch,
    capsys,
):
    result = _probe(
        monkeypatch,
        capsys,
        {
            "available": False,
            "verified": False,
            "reason":
                "probe_timeout",
            "transcript": "",
            "transcript_verified":
                False,
            "output":
                "INTERNAL_TIMEOUT_DETAILS",
        },
    )

    assert result["text"] is None

    assert (
        "Speech recognition timed out."
        in result["output"]
    )

    assert (
        "INTERNAL_TIMEOUT_DETAILS"
        not in result["output"]
    )


def test_google_play_message_is_local_and_clear(
    monkeypatch,
    capsys,
):
    result = _probe(
        monkeypatch,
        capsys,
        {
            "available": False,
            "verified": True,
            "reason":
                "google_play_termux_api_unavailable",
            "transcript": "",
            "transcript_verified":
                False,
            "output":
                "Termux:API is not yet available on Google Play",
        },
    )

    assert result["text"] is None

    assert (
        "Termux:API speech recognition is not available "
        "in this environment."
        in result["output"]
    )

    assert (
        "not yet available on Google Play"
        not in result["output"]
    )


def test_unverified_nonempty_transcript_is_never_echoed(
    monkeypatch,
    capsys,
):
    result = _probe(
        monkeypatch,
        capsys,
        {
            "available": True,
            "verified": True,
            "reason":
                "recognizer_no_match",
            "transcript":
                "UNVERIFIED_SECRET_TEXT",
            "transcript_verified":
                False,
            "output": "",
        },
    )

    assert result["text"] is None

    assert (
        "UNVERIFIED_SECRET_TEXT"
        not in result["output"]
    )


def test_unexpected_backend_reason_does_not_expose_reason_or_output(
    monkeypatch,
    capsys,
):
    result = _probe(
        monkeypatch,
        capsys,
        {
            "available": False,
            "verified": False,
            "reason":
                "INTERNAL_BACKEND_REASON_123",
            "transcript": "",
            "transcript_verified":
                False,
            "output":
                "RAW_INTERNAL_OUTPUT_456",
        },
    )

    assert result["text"] is None

    assert (
        "Speech recognition did not produce "
        "a verified transcript."
        in result["output"]
    )

    assert (
        "INTERNAL_BACKEND_REASON_123"
        not in result["output"]
    )

    assert (
        "RAW_INTERNAL_OUTPUT_456"
        not in result["output"]
    )


def test_probe_exception_does_not_expose_exception_details(
    monkeypatch,
    capsys,
):
    def failing_probe():
        raise RuntimeError(
            "PRIVATE_BACKEND_EXCEPTION_DETAILS"
        )

    monkeypatch.setattr(
        cli,
        "probe_and_record_speech_to_text",
        failing_probe,
    )

    text = cli._voice_input_text()

    output = capsys.readouterr().out

    assert text is None

    assert (
        "Listening..."
        in output
    )

    assert (
        "Speech recognition could not be completed."
        in output
    )

    assert (
        "PRIVATE_BACKEND_EXCEPTION_DETAILS"
        not in output
    )

    assert (
        "RuntimeError"
        not in output
    )
