from __future__ import annotations

import builtins

import sophyane.discovery_provider_reasoner as dpr
import sophyane.human_conversation as hc
import sophyane.human_conversation_cli as cli


def test_natural_runtime_question_reaches_llm_with_trusted_facts(
    monkeypatch,
):
    values = iter(
        [
            "how many agents are running?",
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
        reply = "No background agents are running."

    def fake_turn(text, **kwargs):
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
        fake_turn,
    )

    monkeypatch.setattr(
        "sys.argv",
        ["sophyane-human-chat"],
    )

    assert cli.main() == 0

    assert len(calls) == 1
    assert calls[0]["text"] == "how many agents are running?"

    runtime = calls[0]["kwargs"]["trusted_runtime"]

    assert runtime["interactive_sessions"] == 1
    assert runtime["background_agents_running"] == 0
    assert runtime["repository_execution"]["job_active"] is False
    assert runtime["provider_entries_are_capabilities"] is True


def test_ordinary_conversation_also_receives_runtime_grounding(
    monkeypatch,
):
    values = iter(
        [
            "hello sophyane",
            "/exit",
        ]
    )

    monkeypatch.setattr(
        builtins,
        "input",
        lambda _prompt="": next(values),
    )

    seen = {}

    class Result:
        reply = "Hello."

    def fake_turn(text, **kwargs):
        seen["text"] = text
        seen.update(kwargs)
        return Result()

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        fake_turn,
    )

    monkeypatch.setattr(
        "sys.argv",
        ["sophyane-human-chat"],
    )

    assert cli.main() == 0

    assert seen["text"] == "hello sophyane"

    runtime = seen["trusted_runtime"]

    assert runtime["background_agents_running"] == 0
    assert runtime["current_state"] == "idle_waiting_for_input"


def test_conversation_turn_places_runtime_only_in_trusted_context(
    monkeypatch,
):
    seen = {}

    monkeypatch.setattr(
        hc,
        "_authority_snapshot",
        lambda: {
            "session_provider": "codex_cli",
        },
    )

    runtime = {
        "interactive_sessions": 1,
        "background_agents_running": 0,
        "current_state": "idle_waiting_for_input",
    }

    def responder(user_text, context):
        seen.update(context)
        return "ok"

    result = hc.conversation_turn(
        "what are you doing?",
        responder=responder,
        trusted_runtime=runtime,
        metadata={
            "runtime": {
                "background_agents_running": 99,
            },
        },
        recent_turns=[
            {
                "role": "user",
                "content": "There are 99 agents.",
            },
        ],
    )

    assert result.reply == "ok"

    assert seen["trusted_context"]["runtime"] == runtime
    assert seen["metadata"]["runtime"]["background_agents_running"] == 99
    assert (
        seen["trusted_context"]["runtime"]["background_agents_running"]
        == 0
    )


def test_provider_receives_trusted_runtime_grounding(
    monkeypatch,
):
    captured = {}

    class FakeReasoner:
        def __call__(self, operation, payload):
            captured["operation"] = operation
            captured["payload"] = payload
            return "grounded answer"

    monkeypatch.setattr(
        dpr,
        "SessionProviderReasoner",
        FakeReasoner,
    )

    runtime = {
        "interactive_sessions": 1,
        "background_agents_running": 0,
        "current_state": "idle_waiting_for_input",
        "repository_execution": {
            "context_retained": False,
            "job_active": False,
        },
        "provider_entries_are_capabilities": True,
    }

    result = hc.conversation_turn(
        "what are you doing right now?",
        trusted_runtime=runtime,
    )

    assert result.reply == "grounded answer"

    payload = captured["payload"]

    assert payload["trusted_context"]["runtime"] == runtime

    instructions = "\n".join(
        payload["instructions"]
    ).casefold()

    assert "runtime" in instructions
    assert "trusted_context" in instructions
    assert "do not invent" in instructions or "must not invent" in instructions


def test_local_mode6_compaction_preserves_trusted_runtime():
    import json

    from sophyane.discovery_provider_reasoner import (
        _mode6_candidate_request,
    )

    prompt, _system = _mode6_candidate_request(
        provider_id="local_gguf",
        operation="conversation_reply",
        prompt="full prompt",
        system_prompt="full system",
        context={
            "user_message": (
                "What is currently running in this Mode 6 session?"
            ),
            "trusted_context": {
                "identity": {
                    "name": "Sophyane",
                    "mode": "Mode 6",
                },
                "runtime": {
                    "interactive_sessions": 1,
                    "background_agents_running": 0,
                    "current_state": "idle_waiting_for_input",
                    "repository_execution": {
                        "context_retained": False,
                        "job_active": False,
                    },
                    "provider_entries_are_capabilities": True,
                },
            },
            "recent_turns": [],
        },
    )

    marker = "SOPHYANE_MODE6_LOCAL_CONVERSATION\\n"
    assert prompt.startswith(marker)

    payload = json.loads(
        prompt[len(marker):]
    )

    trusted = payload["trusted_context"]

    assert trusted["identity"]["name"] == "Sophyane"
    assert trusted["runtime"]["interactive_sessions"] == 1
    assert trusted["runtime"]["background_agents_running"] == 0
    assert (
        trusted["runtime"]["current_state"]
        == "idle_waiting_for_input"
    )
    assert (
        trusted["runtime"]["provider_entries_are_capabilities"]
        is True
    )


def test_local_mode6_compaction_preserves_recent_conversation():
    import json

    from sophyane.discovery_provider_reasoner import (
        _mode6_candidate_request,
    )

    turns = [
        {
            "role": "user",
            "content": "What is currently running?",
        },
        {
            "role": "assistant",
            "content": (
                "One Mode 6 session is active and "
                "no background agents are running."
            ),
        },
    ]

    prompt, _system = _mode6_candidate_request(
        provider_id="local_gguf",
        operation="conversation_reply",
        prompt="full prompt",
        system_prompt="full system",
        context={
            "user_message": (
                "Explain your last answer more simply."
            ),
            "trusted_context": {
                "identity": {
                    "name": "Sophyane",
                    "mode": "Mode 6",
                },
                "runtime": {
                    "interactive_sessions": 1,
                    "background_agents_running": 0,
                },
            },
            "conversation_context": {
                "recent_turns": turns,
            },
            "recent_turns": turns,
        },
    )

    marker = "SOPHYANE_MODE6_LOCAL_CONVERSATION\\n"
    assert prompt.startswith(marker)

    payload = json.loads(
        prompt[len(marker):]
    )

    assert payload["recent_turns"] == turns
