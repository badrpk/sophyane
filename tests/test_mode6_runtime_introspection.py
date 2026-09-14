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
        "could you explain your current activity?",
    ],
)
def test_mode6_runtime_questions_reach_llm_with_trusted_runtime(
    monkeypatch,
    capsys,
    question,
):
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

    calls = []

    class Result:
        reply = "No background agents are running right now."

    def fake_conversation_turn(text, **kwargs):
        calls.append(
            {
                "text": text,
                "kwargs": kwargs,
            }
        )
        return Result()

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        fake_conversation_turn,
    )

    monkeypatch.setattr(
        "sys.argv",
        ["sophyane-human-chat"],
    )

    assert cli.main() == 0

    assert len(calls) == 1
    assert calls[0]["text"] == question

    runtime = calls[0]["kwargs"]["trusted_runtime"]

    assert runtime["interactive_sessions"] == 1
    assert runtime["background_agents_running"] == 0
    assert runtime["current_state"] == "idle_waiting_for_input"
    assert runtime["repository_execution"]["job_active"] is False
    assert runtime["provider_entries_are_capabilities"] is True

    output = capsys.readouterr().out.casefold()

    assert "no background agents" in output
    assert "sophyane error:" not in output


def test_provider_capabilities_are_not_reported_as_running_agents(
    monkeypatch,
):
    state = cli._mode6_runtime_state()

    assert state["background_agents_running"] == 0
    assert state["provider_entries_are_capabilities"] is True


def test_retained_execution_context_is_not_active_background_job():
    state = cli._mode6_runtime_state(
        execution_context_active=True,
    )

    repository = state["repository_execution"]

    assert repository["context_retained"] is True
    assert repository["job_active"] is False
    assert state["background_agents_running"] == 0
