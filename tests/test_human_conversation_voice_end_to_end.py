from __future__ import annotations

import sophyane.human_conversation_cli as cli
from sophyane.human_conversation import (
    conversation_turn,
)


def test_verified_voice_transcript_enters_real_conversation_pipeline(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "XERUS_HOME",
        str(tmp_path),
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "nifdu_llm",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_PROVIDER",
        "nifdu_browser",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODEL",
        "chatgpt-browser",
    )

    transcript = (
        "voice end to end integration proof"
    )

    monkeypatch.setattr(
        cli,
        "probe_and_record_speech_to_text",
        lambda: {
            "available": True,
            "verified": True,
            "reason":
                "verified_transcript",
            "transcript":
                transcript,
            "transcript_verified":
                True,
            "output":
                "RAW_OUTPUT_MUST_NOT_MATTER",
        },
    )

    voice_text = (
        cli._voice_input_text()
    )

    assert voice_text == transcript

    seen = {}

    def responder(
        user_text,
        context,
    ):
        seen[
            "user_text"
        ] = user_text

        seen[
            "context"
        ] = context

        return {
            "reply":
                "voice pipeline reply",
        }

    result = conversation_turn(
        voice_text,
        responder=responder,
    )

    assert (
        result.user_text
        == transcript
    )

    assert (
        seen["user_text"]
        == transcript
    )

    assert (
        result.perception[
            "kind"
        ]
        == "language_perception"
    )

    assert (
        result.thought[
            "kind"
        ]
        == "present_conversation_thought"
    )

    assert (
        result.reply
        == "voice pipeline reply"
    )

    assert (
        result.memory_result[
            "exact_recorded"
        ]
        is True
    )

    assert (
        result.authority[
            "session_provider"
        ]
        == "nifdu_browser"
    )

    assert (
        result.authority[
            "provider_switching_allowed"
        ]
        is False
    )


def test_voice_transcript_preserved_exactly_into_conversation_turn(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "XERUS_HOME",
        str(tmp_path),
    )

    transcript = (
        "Please remember Voice Token ZETA 771."
    )

    seen = []

    def responder(
        user_text,
        context,
    ):
        seen.append(
            user_text
        )

        return "ok"

    result = conversation_turn(
        transcript,
        responder=responder,
    )

    assert seen == [
        transcript,
    ]

    assert (
        result.user_text
        == transcript
    )


def test_failed_voice_result_cannot_become_conversation_text(
    monkeypatch,
):
    monkeypatch.setattr(
        cli,
        "probe_and_record_speech_to_text",
        lambda: {
            "available": True,
            "verified": True,
            "reason":
                "recognizer_no_match",
            "transcript":
                "UNVERIFIED_TEXT",
            "transcript_verified":
                False,
            "output":
                "ERROR: ERROR_NO_MATCH",
        },
    )

    assert (
        cli._voice_input_text()
        is None
    )


def test_verified_flag_without_verified_reason_is_insufficient(
    monkeypatch,
):
    monkeypatch.setattr(
        cli,
        "probe_and_record_speech_to_text",
        lambda: {
            "available": True,
            "verified": True,
            "reason":
                "recognizer_no_match",
            "transcript":
                "must not enter conversation",
            "transcript_verified":
                True,
            "output": "",
        },
    )

    assert (
        cli._voice_input_text()
        is None
    )


def test_verified_reason_without_transcript_verified_is_insufficient(
    monkeypatch,
):
    monkeypatch.setattr(
        cli,
        "probe_and_record_speech_to_text",
        lambda: {
            "available": True,
            "verified": True,
            "reason":
                "verified_transcript",
            "transcript":
                "must not enter conversation",
            "transcript_verified":
                False,
            "output": "",
        },
    )

    assert (
        cli._voice_input_text()
        is None
    )
