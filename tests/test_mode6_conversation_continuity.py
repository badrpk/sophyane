import builtins

import pytest

import sophyane.human_conversation as conversation
import sophyane.human_conversation_cli as cli


def test_runtime_grounded_reply_is_available_to_followup(
    monkeypatch,
    capsys,
):
    values = iter(
        [
            "how many agents are running?",
            "explain above reply",
            "/exit",
        ]
    )

    monkeypatch.setattr(
        builtins,
        "input",
        lambda _prompt="": next(values),
    )

    calls = []

    class Result:
        def __init__(self, reply):
            self.reply = reply

    def fake_conversation_turn(
        text,
        **kwargs,
    ):
        calls.append(
            {
                "text": text,
                "kwargs": kwargs,
            }
        )

        if len(calls) == 1:
            return Result(
                "No background agents are running."
            )

        return Result(
            "That means this chat is open, but no "
            "background agent is working."
        )

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        fake_conversation_turn,
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "sophyane-human-chat",
        ],
    )

    assert cli.main() == 0
    assert len(calls) == 2

    first_runtime = (
        calls[0]["kwargs"]["trusted_runtime"]
    )

    assert (
        first_runtime["background_agents_running"]
        == 0
    )

    recent_turns = (
        calls[1]["kwargs"]["recent_turns"]
    )

    assert recent_turns == [
        {
            "role": "user",
            "content": "how many agents are running?",
        },
        {
            "role": "assistant",
            "content": "No background agents are running.",
        },
    ]

    output = capsys.readouterr().out

    assert (
        "That means this chat is open"
        in output
    )

def test_default_mode6_responder_has_stable_sophyane_identity(
    monkeypatch,
):
    """Provider prompt must anchor the assistant as Sophyane, never Sophia."""

    import sophyane.discovery_provider_reasoner as reasoner_module

    seen = {}

    class FakeReasoner:
        def __call__(
            self,
            kind,
            payload,
        ):
            seen["kind"] = kind
            seen["payload"] = payload

            return {
                "reply": "I am Sophyane."
            }

    monkeypatch.setattr(
        reasoner_module,
        "SessionProviderReasoner",
        lambda: FakeReasoner(),
    )

    raw = conversation._default_responder(
        (
            "you are human interaction of sophyane "
            "so you should explain everything in "
            "plain simple words"
        ),
        {
            "perception": {},
            "thought": {},
            "authority": {},
            "metadata": {},
        },
    )

    assert raw["reply"] == "I am Sophyane."

    payload = seen["payload"]

    assert (
        seen["kind"]
        == "conversation_reply"
    )

    instructions = "\n".join(
        str(value)
        for value in payload[
            "instructions"
        ]
    )

    assert "Sophyane" in instructions, (
        "conversation provider has no explicit "
        "Sophyane identity anchor"
    )

    assert (
        "Sophia" in instructions
        or "do not rename" in instructions.casefold()
        or "never rename" in instructions.casefold()
    ), (
        "conversation provider is not explicitly "
        "prevented from identity drift"
    )
