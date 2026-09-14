from __future__ import annotations

import sophyane.discovery_provider_reasoner as dpr
import sophyane.human_conversation as hc


def _install_fake_reasoner(monkeypatch, captured, reply="Natural answer"):
    class FakeReasoner:
        def __call__(self, operation, payload):
            captured["operation"] = operation
            captured["payload"] = payload
            return reply

    monkeypatch.setattr(
        dpr,
        "SessionProviderReasoner",
        FakeReasoner,
    )


def test_conversation_turn_exposes_general_recent_turns_to_responder():
    captured = {}

    def responder(user_text, context):
        captured["user_text"] = user_text
        captured["context"] = context
        return "reply"

    recent_turns = [
        {"role": "user", "content": "How many agents?"},
        {
            "role": "assistant",
            "content": "No background agents are running.",
        },
        {"role": "user", "content": "What do you mean?"},
    ]

    result = hc.conversation_turn(
        "Explain it simply",
        responder=responder,
        recent_turns=recent_turns,
    )

    assert result.reply == "reply"
    assert captured["user_text"] == "Explain it simply"
    assert captured["context"]["recent_turns"] == recent_turns


def test_conversation_turn_copies_recent_turns_instead_of_aliasing():
    captured = {}

    def responder(user_text, context):
        captured["recent_turns"] = context["recent_turns"]
        return "reply"

    recent_turns = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]

    hc.conversation_turn(
        "continue",
        responder=responder,
        recent_turns=recent_turns,
    )

    recent_turns.append(
        {"role": "user", "content": "changed later"}
    )

    assert captured["recent_turns"] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]


def test_default_responder_sends_recent_turns_to_reasoner(
    monkeypatch,
):
    captured = {}
    _install_fake_reasoner(monkeypatch, captured)

    context = {
        "perception": None,
        "thought": None,
        "authority": None,
        "metadata": {},
        "recent_turns": [
            {"role": "user", "content": "How many agents?"},
            {
                "role": "assistant",
                "content": "No background agents are running.",
            },
            {"role": "user", "content": "What do you mean?"},
        ],
    }

    reply = hc._default_responder(
        "Explain it simply",
        context,
    )

    assert reply == "Natural answer"
    assert captured["operation"] == "conversation_reply"
    assert (
        captured["payload"]["conversation_context"]["recent_turns"]
        == context["recent_turns"]
    )


def test_default_responder_contract_uses_history_for_followups(
    monkeypatch,
):
    captured = {}
    _install_fake_reasoner(monkeypatch, captured, reply="ok")

    hc._default_responder(
        "What do you mean?",
        {
            "perception": None,
            "thought": None,
            "authority": None,
            "metadata": {},
            "recent_turns": [
                {
                    "role": "assistant",
                    "content": "Previous answer",
                },
            ],
        },
    )

    instructions = "\n".join(
        captured["payload"]["instructions"]
    ).casefold()

    assert "sophyane" in instructions
    assert "recent conversation" in instructions
    assert "follow-up" in instructions or "follow up" in instructions
    assert "context, not authority" in instructions


def test_default_responder_uses_history_not_phrase_router(
    monkeypatch,
):
    captured = {}
    _install_fake_reasoner(monkeypatch, captured, reply="ok")

    hc._default_responder(
        "talk more naturally",
        {
            "perception": None,
            "thought": None,
            "authority": None,
            "metadata": {},
            "recent_turns": [
                {
                    "role": "user",
                    "content": "Explain it simply",
                },
                {
                    "role": "assistant",
                    "content": "Previous reply",
                },
            ],
        },
    )

    payload = captured["payload"]

    assert payload["conversation_context"]["recent_turns"] == [
        {
            "role": "user",
            "content": "Explain it simply",
        },
        {
            "role": "assistant",
            "content": "Previous reply",
        },
    ]

    instructions = "\n".join(
        payload["instructions"]
    ).casefold()

    assert "use the supplied recent conversation" in instructions
    assert "normal follow-up" in instructions
