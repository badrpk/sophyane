def test_salient_conversation_is_sparse_but_unverified(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "XERUS_HOME",
        str(tmp_path),
    )

    from sophyane.conversation_memory import (
        persist_conversation_turn,
        recall_conversation_memories,
    )

    token = (
        "ORBITAL_CEDAR_9137"
    )

    result = persist_conversation_turn(
        user_text=(
            "Please remember that my current "
            "project marker is "
            + token
            + " and I prefer bounded verification."
        ),
        assistant_text=(
            "I will use that preference as "
            "conversation context."
        ),
    )

    assert result["ok"] is True
    assert result[
        "exact_recorded"
    ] is True

    assert result[
        "sparse_memory_created"
    ] is True

    memory = result[
        "sparse_memory"
    ]

    assert memory[
        "experienced"
    ] is True

    assert memory[
        "verified"
    ] is False

    assert memory[
        "trusted_world_knowledge"
    ] is False

    assert memory[
        "instruction_authority"
    ] is False

    rows = recall_conversation_memories(
        token,
        limit=5,
    )

    assert rows

    assert token.casefold() in (
        rows[0][
            "user_gist"
        ].casefold()
    )


def test_trivial_greeting_not_forced_into_sparse_memory(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "XERUS_HOME",
        str(tmp_path),
    )

    from sophyane.conversation_memory import (
        persist_conversation_turn,
    )

    result = persist_conversation_turn(
        user_text="Hi",
        assistant_text="Hello!",
    )

    assert result[
        "exact_recorded"
    ] is True

    assert result[
        "sparse_memory_created"
    ] is False
