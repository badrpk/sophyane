from __future__ import annotations

import sys

import sophyane.human_conversation_cli as cli


class _Turn:
    def __init__(self, reply: str):
        self.reply = reply


def _run(
    monkeypatch,
    capsys,
    *,
    inputs,
    sensor_report,
):
    values = iter(inputs)

    monkeypatch.setattr(
        cli,
        "input",
        lambda prompt="": next(values),
        raising=False,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["sophyane-human-chat"],
    )

    stt_calls = []

    monkeypatch.setattr(
        cli,
        "probe_and_record_speech_to_text",
        lambda: stt_calls.append(True),
    )

    conversation_calls = []

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        lambda text: (
            conversation_calls.append(text)
            or _Turn("ok")
        ),
    )

    status_calls = []

    def fake_status():
        status_calls.append(True)
        return sensor_report

    monkeypatch.setattr(
        cli,
        "native_sensor_capabilities",
        fake_status,
    )

    evidence_calls = []

    def fake_attach(report):
        evidence_calls.append(True)
        return report

    monkeypatch.setattr(
        cli,
        "attach_sensor_probe_evidence",
        fake_attach,
    )

    rc = cli.main()

    return {
        "rc": rc,
        "output": capsys.readouterr().out,
        "stt_calls": stt_calls,
        "conversation_calls": conversation_calls,
        "status_calls": status_calls,
        "evidence_calls": evidence_calls,
    }


def test_voice_status_is_read_only(
    monkeypatch,
    capsys,
):
    report = {
        "capabilities": {
            "speech_to_text": {
                "available": False,
                "verified": False,
                "reason": "active_probe_required",
                "last_probe": {
                    "available": True,
                    "verified": True,
                    "reason": "verified_transcript",
                    "fresh": True,
                    "current_platform_match": True,
                    "age_seconds": 4.2,
                    "freshness_ttl_seconds": 300,
                },
            },
        },
    }

    result = _run(
        monkeypatch,
        capsys,
        inputs=[
            "/voice-status",
            "/exit",
        ],
        sensor_report=report,
    )

    assert result["rc"] == 0
    assert result["stt_calls"] == []
    assert result["conversation_calls"] == []
    assert len(result["status_calls"]) == 1
    assert len(result["evidence_calls"]) == 1


def test_voice_status_does_not_promote_discovery(
    monkeypatch,
    capsys,
):
    report = {
        "capabilities": {
            "speech_to_text": {
                "available": False,
                "verified": False,
                "reason": "active_probe_required",
                "last_probe": {
                    "available": True,
                    "verified": True,
                    "reason": "verified_transcript",
                    "fresh": True,
                    "current_platform_match": True,
                    "age_seconds": 1.0,
                    "freshness_ttl_seconds": 300,
                },
            },
        },
    }

    result = _run(
        monkeypatch,
        capsys,
        inputs=[
            "/voice-status",
            "/exit",
        ],
        sensor_report=report,
    )

    output = result["output"]

    assert "Discovery available: no" in output
    assert "Discovery verified: no" in output
    assert "Discovery reason: active_probe_required" in output

    assert "Last probe fresh: yes" in output
    assert "Platform match: yes" in output
    assert "Last probe reason: verified_transcript" in output


def test_voice_status_without_cached_probe(
    monkeypatch,
    capsys,
):
    report = {
        "capabilities": {
            "speech_to_text": {
                "available": False,
                "verified": False,
                "reason": "active_probe_required",
            },
        },
    }

    result = _run(
        monkeypatch,
        capsys,
        inputs=[
            "/voice-status",
            "/exit",
        ],
        sensor_report=report,
    )

    assert (
        "Last probe: none"
        in result["output"]
    )


def test_normal_text_still_does_not_read_voice_status(
    monkeypatch,
    capsys,
):
    report = {
        "capabilities": {
            "speech_to_text": {
                "available": False,
                "verified": False,
                "reason": "active_probe_required",
            },
        },
    }

    result = _run(
        monkeypatch,
        capsys,
        inputs=[
            "hello",
            "/exit",
        ],
        sensor_report=report,
    )

    assert result["status_calls"] == []
    assert result["evidence_calls"] == []
    assert result["stt_calls"] == []

    assert result["conversation_calls"] == [
        "hello",
    ]
