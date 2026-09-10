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


def test_clear_visual_question_requests_camera():
    assert (
        cli._automatic_perception_intent(
            "what do you see?"
        )
        == "camera"
    )

    assert (
        cli._automatic_perception_intent(
            "can you see what is in front of me?"
        )
        == "camera"
    )

    assert (
        cli._automatic_perception_intent(
            "look around and tell me what you see"
        )
        == "camera"
    )

    assert (
        cli._automatic_perception_intent(
            "use your camera and tell me what is here"
        )
        == "camera"
    )


def test_camera_discussion_does_not_automatically_capture():
    assert (
        cli._automatic_perception_intent(
            "my camera is expensive"
        )
        is None
    )

    assert (
        cli._automatic_perception_intent(
            "explain how a camera works"
        )
        is None
    )

    assert (
        cli._automatic_perception_intent(
            "the camera has four lenses"
        )
        is None
    )


def test_ordinary_conversation_does_not_activate_sensor():
    assert (
        cli._automatic_perception_intent(
            "how are you?"
        )
        is None
    )

    assert (
        cli._automatic_perception_intent(
            "tell me about Islamabad"
        )
        is None
    )


def test_hearing_is_not_falsely_mapped_to_stt():
    # Ambient/raw-audio understanding has not yet
    # been verified as a multimodal provider path.
    assert (
        cli._automatic_perception_intent(
            "what do you hear?"
        )
        is None
    )


def test_natural_visual_question_activates_camera(
    monkeypatch,
    capsys,
):
    values = iter(
        [
            "what do you see?",
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
                "/tmp/verified-camera.jpg",
                {
                    "input_mode":
                        "camera",
                    "perception_trigger":
                        "automatic_visual_intent",
                    "visual_artifact": {
                        "backend":
                            "android_camera_activity",
                    },
                },
            )
        ),
    )

    turns = []

    def fake_turn(
        text,
        **kwargs,
    ):
        turns.append(
            (
                text,
                kwargs,
            )
        )

        return _Turn(
            "I see a red cup."
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

    assert len(
        camera_calls
    ) == 1

    assert len(
        turns
    ) == 1

    text, kwargs = turns[0]

    assert (
        text
        == "what do you see?"
    )

    assert (
        kwargs[
            "visual_artifact_path"
        ]
        == "/tmp/verified-camera.jpg"
    )

    assert (
        kwargs[
            "metadata"
        ][
            "perception_trigger"
        ]
        == "automatic_visual_intent"
    )

    assert (
        "I see a red cup."
        in output
    )


def test_failed_automatic_camera_capture_never_calls_provider(
    monkeypatch,
    capsys,
):
    values = iter(
        [
            "what do you see?",
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
    )

    turns = []

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        lambda *args, **kwargs: (
            turns.append(
                (
                    args,
                    kwargs,
                )
            )
            or _Turn("must not happen")
        ),
    )

    assert cli.main() == 0

    capsys.readouterr()

    assert turns == []


def test_unrelated_typed_turn_never_activates_camera(
    monkeypatch,
    capsys,
):
    values = iter(
        [
            "how are you?",
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

    cameras = []

    monkeypatch.setattr(
        cli,
        "_camera_visual_input",
        lambda: cameras.append(
            True
        ),
    )

    turns = []

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        lambda text: (
            turns.append(text)
            or _Turn("fine")
        ),
    )

    assert cli.main() == 0

    capsys.readouterr()

    assert cameras == []

    assert turns == [
        "how are you?"
    ]


def test_explicit_see_still_works(
    monkeypatch,
    capsys,
):
    values = iter(
        [
            "/see What is on the table?",
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
            "/tmp/camera.jpg",
            {
                "input_mode":
                    "camera",
                "visual_artifact": {},
            },
        ),
    )

    seen = []

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        lambda text, **kwargs: (
            seen.append(
                (
                    text,
                    kwargs,
                )
            )
            or _Turn("object")
        ),
    )

    assert cli.main() == 0

    capsys.readouterr()

    assert (
        seen[0][0]
        == "What is on the table?"
    )


def test_direct_visual_ability_questions_request_camera():
    for text in (
        "do you see?",
        "do you see",
        "can you see?",
        "can you see",
        "are you able to see?",
        "are you able to see",
        "can you look?",
        "can you look around?",
    ):
        assert (
            cli._automatic_perception_intent(
                text
            )
            == "camera"
        )


def test_metaphorical_see_questions_do_not_activate_camera():
    for text in (
        "do you see why this failed?",
        "do you see my point?",
        "can you see why I am concerned?",
        "I see what you mean",
        "you see, this is the problem",
    ):
        assert (
            cli._automatic_perception_intent(
                text
            )
            is None
        )


def test_live_style_do_you_see_routes_camera(
    monkeypatch,
    capsys,
):
    import builtins
    import sys

    values = iter(
        [
            "do you see?",
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
            camera_calls.append(True)
            or (
                "/tmp/camera.jpg",
                {
                    "input_mode":
                        "camera",
                    "visual_artifact": {},
                },
            )
        ),
    )

    turns = []

    class Turn:
        reply = "visual reply"

    def fake_turn(
        text,
        **kwargs,
    ):
        turns.append(
            (
                text,
                kwargs,
            )
        )

        return Turn()

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        fake_turn,
    )

    assert cli.main() == 0

    capsys.readouterr()

    assert camera_calls == [
        True
    ]

    assert (
        turns[0][0]
        == "do you see?"
    )

    assert (
        turns[0][1][
            "visual_artifact_path"
        ]
        == "/tmp/camera.jpg"
    )
