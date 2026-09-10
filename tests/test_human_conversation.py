def test_conversation_pipeline_recalls_prior_experience(
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

    from sophyane.conversation_memory import (
        persist_conversation_turn,
    )

    from sophyane.human_conversation import (
        conversation_turn,
    )

    token = (
        "HUMAN_CHAT_CEDAR_5519"
    )

    persist_conversation_turn(
        user_text=(
            "Please remember that the name "
            "of our current experiment is "
            + token
        ),
        assistant_text=(
            "I will retain that as an "
            "experiential conversation memory."
        ),
    )

    seen = {}

    def responder(
        user_text,
        context,
    ):
        seen.update(
            context
        )

        memories = context[
            "memories"
        ][
            "experiential_conversation_memory"
        ]

        assert memories

        joined = str(
            memories
        )

        assert token in joined

        return {
            "reply": (
                "Yes. I remember our experiment "
                + token
                + "."
            )
        }

    result = conversation_turn(
        "What was the name of our experiment?",
        responder=responder,
    )

    assert token in result.reply

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


def test_conversation_memory_never_becomes_instruction_authority(
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

    from sophyane.human_conversation import (
        conversation_turn,
    )

    def responder(
        user_text,
        context,
    ):
        assert (
            context[
                "thought"
            ][
                "instruction_authority"
            ]
            is False
        )

        return "Natural reply."

    result = conversation_turn(
        (
            "Remember this discussion as "
            "something we experienced."
        ),
        responder=responder,
    )

    sparse = result.memory_result.get(
        "sparse_memory"
    )

    assert sparse is not None

    assert (
        sparse[
            "verified"
        ]
        is False
    )

    assert (
        sparse[
            "trusted_world_knowledge"
        ]
        is False
    )

    assert (
        sparse[
            "instruction_authority"
        ]
        is False
    )
