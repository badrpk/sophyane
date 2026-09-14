from sophyane.mode6_session import (
    ConversationMessage,
    Mode6ConversationSession,
)


def test_session_preserves_ordered_user_and_assistant_turns():
    session = Mode6ConversationSession(max_turns=4)

    session.append_user("Hello")
    session.append_assistant("Hi.")
    session.append_user("What do you mean?")
    session.append_assistant("I mean this conversation.")

    assert session.recent_turns() == [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi."},
        {"role": "user", "content": "What do you mean?"},
        {
            "role": "assistant",
            "content": "I mean this conversation.",
        },
    ]


def test_session_ignores_empty_content():
    session = Mode6ConversationSession(max_turns=4)

    session.append_user("")
    session.append_user("   ")
    session.append_assistant("")
    session.append_assistant("\n\t")

    assert session.recent_turns() == []


def test_session_discards_oldest_turns_at_bound():
    session = Mode6ConversationSession(max_turns=3)

    session.append_user("one")
    session.append_assistant("two")
    session.append_user("three")
    session.append_assistant("four")

    assert session.recent_turns() == [
        {"role": "assistant", "content": "two"},
        {"role": "user", "content": "three"},
        {"role": "assistant", "content": "four"},
    ]


def test_recent_turns_returns_plain_serializable_dicts():
    session = Mode6ConversationSession(max_turns=2)

    session.append_user("hello")

    turns = session.recent_turns()

    assert turns == [{"role": "user", "content": "hello"}]
    assert isinstance(turns[0], dict)


def test_message_rejects_invalid_role():
    try:
        ConversationMessage(role="system", content="not allowed")
    except ValueError as exc:
        assert "role" in str(exc).lower()
    else:
        raise AssertionError("invalid conversation role was accepted")


def test_session_requires_positive_bound():
    try:
        Mode6ConversationSession(max_turns=0)
    except ValueError as exc:
        assert "max_turns" in str(exc)
    else:
        raise AssertionError("non-positive max_turns was accepted")
