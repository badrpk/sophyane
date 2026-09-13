import builtins

import pytest

import sophyane.human_conversation_cli as cli


@pytest.mark.parametrize(
    "question",
    [
        "how many agents sophyane is running?",
        "what is name, purpose, job and status of this running agent?",
        "is it doing something now or it will do in future?",
        "what it is doing?",
    ],
)
def test_mode6_runtime_status_questions_do_not_reach_conversation_llm(
    monkeypatch,
    capsys,
    question,
):
    """Runtime state must come from Sophyane, not LLM speculation."""

    values = iter(
        [
            question,
            "/exit",
        ]
    )

    monkeypatch.setattr(
        builtins,
        "input",
        lambda _prompt="": next(values),
    )

    def forbidden_conversation_turn(*args, **kwargs):
        raise AssertionError(
            "runtime status question reached conversational LLM"
        )

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        forbidden_conversation_turn,
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "sophyane-human-chat",
        ],
    )

    assert cli.main() == 0

    output = capsys.readouterr().out.casefold()

    assert "sophyane error:" not in output
    assert (
        "idle" in output
        or "waiting" in output
        or "no active" in output
    )


def test_mode6_runtime_status_does_not_claim_provider_chain_is_agent_count(
    monkeypatch,
    capsys,
):
    """Available providers are not concurrently running agents."""

    values = iter(
        [
            "how many agents sophyane is running?",
            "/exit",
        ]
    )

    monkeypatch.setattr(
        builtins,
        "input",
        lambda _prompt="": next(values),
    )

    def forbidden_conversation_turn(*args, **kwargs):
        raise AssertionError(
            "agent-count question reached conversational LLM"
        )

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        forbidden_conversation_turn,
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "sophyane-human-chat",
        ],
    )

    assert cli.main() == 0

    output = capsys.readouterr().out.casefold()

    assert "codex_cli -> nifdu_browser -> local_gguf" not in output
    assert (
        "background" in output
        or "active execution" in output
        or "interactive session" in output
    )
