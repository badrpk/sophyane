from __future__ import annotations

import builtins
import json
import sys
from pathlib import Path

import pytest

import sophyane.human_conversation as hc
import sophyane.human_conversation_cli as cli

from sophyane.discovery_provider_reasoner import (
    SessionProviderReasoner,
)
from sophyane.providers.nifdu_browser import (
    NifduBrowserProvider,
    ProviderError,
)


class _Turn:
    def __init__(
        self,
        reply: str,
    ):
        self.reply = reply


def _verified_camera_result(
    path: Path,
):
    return {
        "id": "camera_capture",
        "command": "am",
        "command_path": "/mock/am",
        "command_present": True,
        "available": True,
        "verified": True,
        "backend": "android_camera_activity",
        "reason": "verified_capture",
        "artifact_path": str(path),
        "artifact_bytes": 123456,
        "artifact_verified": True,
        "image_verified": True,
        "image_format": "JPEG",
        "image_width": 4000,
        "image_height": 2252,
        "jpeg_soi_verified": True,
        "jpeg_eoi_present": True,
        "pixel_decode_verified": True,
        "artifact_sha256": "a" * 64,
        "process_returncode": 0,
        "evidence_recorded": True,
        "evidence_observed_at":
            "2026-09-08T13:00:00+00:00",
    }


def test_conversation_turn_exposes_visual_path_only_to_responder(
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

    image = (
        tmp_path
        / "camera.jpg"
    )

    image.write_bytes(
        b"not-used-by-this-test"
    )

    seen = {}

    def responder(
        user_text,
        context,
    ):
        seen.update(
            context
        )

        return {
            "reply": "I can see it."
        }

    result = hc.conversation_turn(
        "What do you see?",
        responder=responder,
        visual_artifact_path=str(image),
        metadata={
            "input_mode": "camera",
        },
    )

    assert (
        seen[
            "visual_artifact_path"
        ]
        == str(image)
    )

    assert (
        result.reply
        == "I can see it."
    )

    # The transient transport path must not be added
    # automatically to persisted metadata.
    assert (
        result.memory_result[
            "exact_recorded"
        ]
        is True
    )


def test_default_responder_forwards_visual_path_as_transient_provider_option(
    monkeypatch,
):
    seen = {}

    class FakeReasoner:
        def __call__(
            self,
            operation,
            payload,
        ):
            seen[
                "operation"
            ] = operation

            seen[
                "payload"
            ] = payload

            return {
                "reply": "visual reply"
            }

    import sophyane.discovery_provider_reasoner as dpr

    monkeypatch.setattr(
        dpr,
        "SessionProviderReasoner",
        FakeReasoner,
    )

    result = hc._default_responder(
        "What is visible?",
        {
            "perception": {},
            "thought": {},
            "authority": {
                "session_provider":
                    "nifdu_browser",
            },
            "visual_artifact_path":
                "/tmp/verified-camera.jpg",
        },
    )

    assert result == {
        "reply": "visual reply"
    }

    assert (
        seen[
            "payload"
        ][
            "_provider_image_path"
        ]
        == "/tmp/verified-camera.jpg"
    )


def test_session_reasoner_forwards_image_only_to_locked_nifdu(
    monkeypatch,
):
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

    calls = []

    class FakeProvider:
        def generate(
            self,
            prompt,
            system_prompt="",
            *,
            image_path=None,
        ):
            calls.append(
                {
                    "prompt": prompt,
                    "system_prompt":
                        system_prompt,
                    "image_path":
                        image_path,
                }
            )

            return json.dumps(
                {
                    "reply": "seen"
                }
            )

    reasoner = SessionProviderReasoner(
        provider_factory=lambda: FakeProvider(),
    )

    response = reasoner(
        "conversation_reply",
        {
            "objective":
                "Have a natural conversation.",
            "user_message":
                "What do you see?",
            "_provider_image_path":
                "/tmp/verified-camera.jpg",
            "return_schema": {
                "reply": "string",
            },
        },
    )

    assert calls

    assert (
        calls[0][
            "image_path"
        ]
        == "/tmp/verified-camera.jpg"
    )

    # Transport path is not serialized into
    # the textual provider prompt.
    assert (
        "/tmp/verified-camera.jpg"
        not in calls[0][
            "prompt"
        ]
    )

    assert "seen" in response


def test_nifdu_provider_passes_image_path_to_two_argument_bridge(
    monkeypatch,
    tmp_path,
):
    module = (
        tmp_path
        / "bridge.py"
    )

    module.write_text(
        """
def ask(prompt, image=None):
    return "IMAGE=" + str(image)
""".lstrip(),
        encoding="utf-8",
    )

    selection = (
        tmp_path
        / "selection.json"
    )

    selection.write_text(
        json.dumps(
            {
                "module":
                    str(module),
                "kind":
                    "function",
                "name":
                    "ask",
                "args": [
                    "prompt",
                    "image",
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv(
        "SOPHYANE_NIFDU_CALLABLE_FILE",
        str(selection),
    )

    provider = (
        NifduBrowserProvider()
    )

    response = provider.generate(
        "look",
        image_path=
            "/tmp/camera.jpg",
    )

    assert (
        "/tmp/camera.jpg"
        in response
    )


def test_nifdu_provider_never_silently_drops_requested_image(
    monkeypatch,
    tmp_path,
):
    module = (
        tmp_path
        / "bridge.py"
    )

    module.write_text(
        """
def ask(prompt):
    return "text only"
""".lstrip(),
        encoding="utf-8",
    )

    selection = (
        tmp_path
        / "selection.json"
    )

    selection.write_text(
        json.dumps(
            {
                "module":
                    str(module),
                "kind":
                    "function",
                "name":
                    "ask",
                "args": [
                    "prompt",
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv(
        "SOPHYANE_NIFDU_CALLABLE_FILE",
        str(selection),
    )

    provider = (
        NifduBrowserProvider()
    )

    with pytest.raises(
        ProviderError,
        match=(
            "image"
        ),
    ):
        provider.generate(
            "look",
            image_path=
                "/tmp/camera.jpg",
        )


def test_camera_visual_input_requires_verified_pixel_artifact(
    monkeypatch,
    tmp_path,
):
    image = (
        tmp_path
        / "camera.jpg"
    )

    image.write_bytes(
        b"verified-placeholder"
    )

    calls = []

    monkeypatch.setattr(
        cli,
        "probe_and_record_camera_capture",
        lambda: (
            calls.append(True)
            or _verified_camera_result(
                image
            )
        ),
        raising=False,
    )

    result = (
        cli._camera_visual_input()
    )

    assert len(calls) == 1
    assert result is not None

    path, metadata = result

    assert path == str(image)

    assert (
        metadata[
            "input_mode"
        ]
        == "camera"
    )

    visual = metadata[
        "visual_artifact"
    ]

    assert (
        visual[
            "backend"
        ]
        == "android_camera_activity"
    )

    assert (
        visual[
            "artifact_sha256"
        ]
        == "a" * 64
    )

    # Persist bounded provenance, not the
    # filesystem transport path.
    assert (
        "artifact_path"
        not in visual
    )


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("available", False),
        ("verified", False),
        (
            "reason",
            "no_new_camera_artifact",
        ),
        (
            "artifact_verified",
            False,
        ),
        (
            "image_verified",
            False,
        ),
        (
            "pixel_decode_verified",
            False,
        ),
    ],
)
def test_camera_visual_input_rejects_unverified_capture(
    monkeypatch,
    tmp_path,
    field,
    bad_value,
):
    image = (
        tmp_path
        / "camera.jpg"
    )

    image.write_bytes(
        b"placeholder"
    )

    result = (
        _verified_camera_result(
            image
        )
    )

    result[
        field
    ] = bad_value

    monkeypatch.setattr(
        cli,
        "probe_and_record_camera_capture",
        lambda: result,
        raising=False,
    )

    assert (
        cli._camera_visual_input()
        is None
    )


def test_see_activates_camera_then_enters_conversation_with_image(
    monkeypatch,
    capsys,
    tmp_path,
):
    image = (
        tmp_path
        / "camera.jpg"
    )

    image.write_bytes(
        b"placeholder"
    )

    values = iter(
        [
            "/see",
            "/exit",
        ]
    )

    monkeypatch.setattr(
        builtins,
        "input",
        lambda prompt="": next(
            values
        ),
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sophyane-human-chat",
        ],
    )

    camera_calls = []

    monkeypatch.setattr(
        cli,
        "_camera_visual_input",
        lambda: (
            camera_calls.append(
                True
            )
            or (
                str(image),
                {
                    "input_mode":
                        "camera",
                    "visual_artifact": {
                        "backend":
                            "android_camera_activity",
                    },
                },
            )
        ),
        raising=False,
    )

    conversation_calls = []

    def fake_turn(
        text,
        **kwargs,
    ):
        conversation_calls.append(
            (
                text,
                kwargs,
            )
        )

        return _Turn(
            "visual answer"
        )

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        fake_turn,
    )

    assert cli.main() == 0

    output = (
        capsys.readouterr().out
    )

    assert len(camera_calls) == 1

    assert len(
        conversation_calls
    ) == 1

    text, kwargs = (
        conversation_calls[0]
    )

    assert (
        text
        == (
            "Describe what you can see "
            "in this camera image."
        )
    )

    assert (
        kwargs[
            "visual_artifact_path"
        ]
        == str(image)
    )

    assert (
        kwargs[
            "metadata"
        ][
            "input_mode"
        ]
        == "camera"
    )

    assert (
        "visual answer"
        in output
    )


def test_see_custom_question_is_preserved(
    monkeypatch,
    capsys,
    tmp_path,
):
    image = (
        tmp_path
        / "camera.jpg"
    )

    image.write_bytes(
        b"placeholder"
    )

    values = iter(
        [
            "/see What object is on the table?",
            "/exit",
        ]
    )

    monkeypatch.setattr(
        builtins,
        "input",
        lambda prompt="": next(
            values
        ),
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sophyane-human-chat",
        ],
    )

    monkeypatch.setattr(
        cli,
        "_camera_visual_input",
        lambda: (
            str(image),
            {
                "input_mode":
                    "camera",
                "visual_artifact": {},
            },
        ),
        raising=False,
    )

    seen = []

    def fake_turn(
        text,
        **kwargs,
    ):
        seen.append(
            (
                text,
                kwargs,
            )
        )

        return _Turn(
            "answer"
        )

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        fake_turn,
    )

    assert cli.main() == 0

    capsys.readouterr()

    assert (
        seen[0][0]
        == "What object is on the table?"
    )


def test_failed_see_never_calls_conversation(
    monkeypatch,
    capsys,
):
    values = iter(
        [
            "/see",
            "/exit",
        ]
    )

    monkeypatch.setattr(
        builtins,
        "input",
        lambda prompt="": next(
            values
        ),
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sophyane-human-chat",
        ],
    )

    monkeypatch.setattr(
        cli,
        "_camera_visual_input",
        lambda: None,
        raising=False,
    )

    calls = []

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        lambda *args, **kwargs: (
            calls.append(True)
            or _Turn("bad")
        ),
    )

    assert cli.main() == 0

    capsys.readouterr()

    assert calls == []


def test_typed_turn_never_activates_camera(
    monkeypatch,
    capsys,
):
    values = iter(
        [
            "hello",
            "/exit",
        ]
    )

    monkeypatch.setattr(
        builtins,
        "input",
        lambda prompt="": next(
            values
        ),
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sophyane-human-chat",
        ],
    )

    camera_calls = []

    monkeypatch.setattr(
        cli,
        "_camera_visual_input",
        lambda: camera_calls.append(
            True
        ),
        raising=False,
    )

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        lambda text: _Turn(
            "ok"
        ),
    )

    assert cli.main() == 0

    capsys.readouterr()

    assert camera_calls == []
