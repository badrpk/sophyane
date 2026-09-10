from __future__ import annotations

import builtins
import sys

import sophyane.human_conversation_cli as cli


class _Turn:
    def __init__(
        self,
        reply: str,
    ):
        self.reply = reply


def _run_cli(
    monkeypatch,
    capsys,
    *,
    inputs,
    stt_result=None,
):
    values = iter(inputs)

    monkeypatch.setattr(
        builtins,
        "input",
        lambda prompt="": next(values),
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sophyane-human-chat",
        ],
    )

    stt_calls = []

    def fake_stt():
        stt_calls.append(True)

        if stt_result is None:
            raise AssertionError(
                "STT must not be called"
            )

        return dict(
            stt_result
        )

    monkeypatch.setattr(
        cli,
        "probe_and_record_speech_to_text",
        fake_stt,
    )

    conversation_calls = []

    def fake_turn(text):
        conversation_calls.append(
            text
        )

        return _Turn(
            "reply:" + text
        )

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        fake_turn,
    )

    rc = cli.main()

    output = capsys.readouterr().out

    return {
        "rc": rc,
        "output": output,
        "stt_calls": len(
            stt_calls
        ),
        "conversation_calls":
            conversation_calls,
    }


def test_typed_input_never_activates_stt(
    monkeypatch,
    capsys,
):
    result = _run_cli(
        monkeypatch,
        capsys,
        inputs=[
            "hello there",
            "/exit",
        ],
    )

    assert result["rc"] == 0
    assert result["stt_calls"] == 0
    assert (
        result[
            "conversation_calls"
        ]
        == [
            "hello there",
        ]
    )


def test_voice_verified_transcript_uses_existing_conversation_path(
    monkeypatch,
    capsys,
):
    result = _run_cli(
        monkeypatch,
        capsys,
        inputs=[
            "/voice",
            "/exit",
        ],
        stt_result={
            "available": True,
            "verified": True,
            "reason":
                "verified_transcript",
            "transcript":
                "hello from voice",
            "transcript_verified":
                True,
        },
    )

    assert result["rc"] == 0
    assert result["stt_calls"] == 1

    assert (
        result[
            "conversation_calls"
        ]
        == [
            "hello from voice",
        ]
    )

    assert (
        "You (voice): hello from voice"
        in result["output"]
    )


def test_voice_no_match_does_not_call_conversation(
    monkeypatch,
    capsys,
):
    result = _run_cli(
        monkeypatch,
        capsys,
        inputs=[
            "/voice",
            "/exit",
        ],
        stt_result={
            "available": True,
            "verified": True,
            "reason":
                "recognizer_no_match",
            "transcript": "",
            "transcript_verified":
                False,
        },
    )

    assert result["stt_calls"] == 1
    assert (
        result[
            "conversation_calls"
        ]
        == []
    )

    assert (
        "No speech was recognized."
        in result["output"]
    )


def test_voice_permission_denied_does_not_call_conversation(
    monkeypatch,
    capsys,
):
    result = _run_cli(
        monkeypatch,
        capsys,
        inputs=[
            "/voice",
            "/exit",
        ],
        stt_result={
            "available": False,
            "verified": True,
            "reason":
                "permission_denied",
            "transcript": "",
            "transcript_verified":
                False,
        },
    )

    assert (
        result[
            "conversation_calls"
        ]
        == []
    )

    assert (
        "Microphone permission is not available."
        in result["output"]
    )


def test_voice_timeout_does_not_call_conversation(
    monkeypatch,
    capsys,
):
    result = _run_cli(
        monkeypatch,
        capsys,
        inputs=[
            "/voice",
            "/exit",
        ],
        stt_result={
            "available": False,
            "verified": False,
            "reason":
                "probe_timeout",
            "transcript": "",
            "transcript_verified":
                False,
        },
    )

    assert (
        result[
            "conversation_calls"
        ]
        == []
    )

    assert (
        "Speech recognition timed out."
        in result["output"]
    )


def test_voice_google_play_unavailable_does_not_call_conversation(
    monkeypatch,
    capsys,
):
    result = _run_cli(
        monkeypatch,
        capsys,
        inputs=[
            "/voice",
            "/exit",
        ],
        stt_result={
            "available": False,
            "verified": True,
            "reason":
                "google_play_termux_api_unavailable",
            "transcript": "",
            "transcript_verified":
                False,
        },
    )

    assert (
        result[
            "conversation_calls"
        ]
        == []
    )

    assert (
        "Termux:API speech recognition is not available"
        in result["output"]
    )


def test_voice_recognizer_error_does_not_call_conversation(
    monkeypatch,
    capsys,
):
    result = _run_cli(
        monkeypatch,
        capsys,
        inputs=[
            "/voice",
            "/exit",
        ],
        stt_result={
            "available": False,
            "verified": True,
            "reason":
                "recognizer_error",
            "transcript": "",
            "transcript_verified":
                False,
        },
    )

    assert (
        result[
            "conversation_calls"
        ]
        == []
    )

    assert (
        "Speech recognizer returned an error."
        in result["output"]
    )


def test_voice_unverified_nonempty_text_is_never_forwarded(
    monkeypatch,
    capsys,
):
    result = _run_cli(
        monkeypatch,
        capsys,
        inputs=[
            "/voice",
            "/exit",
        ],
        stt_result={
            "available": True,
            "verified": True,
            "reason":
                "recognizer_no_match",
            "transcript":
                "must never be forwarded",
            "transcript_verified":
                False,
        },
    )

    assert (
        result[
            "conversation_calls"
        ]
        == []
    )


def test_once_mode_never_activates_voice(
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sophyane-human-chat",
            "--once",
            "typed once",
        ],
    )

    stt_calls = []

    monkeypatch.setattr(
        cli,
        "probe_and_record_speech_to_text",
        lambda: stt_calls.append(True),
    )

    conversation_calls = []

    def fake_turn(text):
        conversation_calls.append(
            text
        )
        return _Turn(
            "ok"
        )

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        fake_turn,
    )

    assert cli.main() == 0

    capsys.readouterr()

    assert stt_calls == []

    assert conversation_calls == [
        "typed once",
    ]
