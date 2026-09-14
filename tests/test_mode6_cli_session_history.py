import builtins

import sophyane.human_conversation_cli as cli


def _run_cli(monkeypatch, values, fake_turn):
    iterator = iter(values)

    monkeypatch.setattr(
        builtins,
        "input",
        lambda _prompt="": next(iterator),
    )

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        fake_turn,
    )

    monkeypatch.setattr(
        "sys.argv",
        ["sophyane-human-chat"],
    )

    return cli.main()


def test_runtime_grounded_llm_reply_enters_general_session_history(
    monkeypatch,
):
    calls = []

    class Result:
        def __init__(self, reply):
            self.reply = reply

    def fake_turn(text, **kwargs):
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
            "It means no hidden background worker is active."
        )

    rc = _run_cli(
        monkeypatch,
        [
            "how many agents are running?",
            "what do you mean?",
            "/exit",
        ],
        fake_turn,
    )

    assert rc == 0
    assert len(calls) == 2

    first_runtime = (
        calls[0]["kwargs"]["trusted_runtime"]
    )

    assert (
        first_runtime["background_agents_running"]
        == 0
    )

    history = (
        calls[1]["kwargs"]["recent_turns"]
    )

    assert history == [
        {
            "role": "user",
            "content": "how many agents are running?",
        },
        {
            "role": "assistant",
            "content": "No background agents are running.",
        },
    ]

def test_llm_replies_persist_across_multiple_turns(
    monkeypatch,
):
    calls = []

    class Result:
        def __init__(self, reply):
            self.reply = reply

    def fake_turn(text, **kwargs):
        calls.append(
            {
                "text": text,
                "history": list(
                    kwargs.get(
                        "recent_turns",
                        [],
                    )
                ),
            }
        )

        return Result(
            f"reply-{len(calls)}"
        )

    rc = _run_cli(
        monkeypatch,
        [
            "hello",
            "what did you just say?",
            "say it more naturally",
            "/exit",
        ],
        fake_turn,
    )

    assert rc == 0
    assert len(calls) == 3

    assert calls[0]["history"] == []

    assert calls[1]["history"] == [
        {
            "role": "user",
            "content": "hello",
        },
        {
            "role": "assistant",
            "content": "reply-1",
        },
    ]

    assert calls[2]["history"] == [
        {
            "role": "user",
            "content": "hello",
        },
        {
            "role": "assistant",
            "content": "reply-1",
        },
        {
            "role": "user",
            "content": "what did you just say?",
        },
        {
            "role": "assistant",
            "content": "reply-2",
        },
    ]


def test_empty_input_does_not_enter_session_or_call_llm(
    monkeypatch,
):
    calls = []

    class Result:
        reply = "hello"

    def fake_turn(text, **kwargs):
        calls.append(
            {
                "text": text,
                "history": kwargs.get(
                    "recent_turns",
                ),
            }
        )
        return Result()

    rc = _run_cli(
        monkeypatch,
        [
            "",
            "   ",
            "hello",
            "/exit",
        ],
        fake_turn,
    )

    assert rc == 0
    assert len(calls) == 1
    assert calls[0]["text"] == "hello"
    assert calls[0]["history"] == []
