from __future__ import annotations

import sophyane.discovery_provider_reasoner as dpr
import sophyane.human_conversation as hc


def _observation():
    return {
        "problem": (
            "Mode 6 can repeatedly misunderstand an "
            "ambiguous runtime follow-up."
        ),
        "evidence": [
            "The supplied conversation contains a repeated correction.",
            "Trusted runtime facts conflict with the inferred answer.",
        ],
        "component": "human_conversation",
        "suggested_direction": (
            "Improve contextual grounding before generating the reply."
        ),
        "source_mutation_required": True,
    }


def test_mapping_response_returns_reply_and_normalized_observation(
    monkeypatch,
):
    monkeypatch.setattr(
        hc,
        "_authority_snapshot",
        lambda: {
            "session_provider": "codex_cli",
        },
    )

    result = hc.conversation_turn(
        "why did that happen?",
        responder=lambda _text, _context: {
            "reply": "Because the follow-up was ambiguous.",
            "improvement_observation": _observation(),
        },
    )

    assert result.reply == "Because the follow-up was ambiguous."

    observation = result.improvement_observation

    assert observation is not None
    assert observation.problem.startswith("Mode 6")
    assert observation.component == "human_conversation"
    assert observation.evidence == (
        "The supplied conversation contains a repeated correction.",
        "Trusted runtime facts conflict with the inferred answer.",
    )
    assert observation.suggested_direction.startswith("Improve")
    assert observation.source_mutation_required is True

    assert observation.trusted is False
    assert observation.instruction_authority is False
    assert observation.mutation_authority is False


def test_json_string_response_preserves_optional_observation(
    monkeypatch,
):
    monkeypatch.setattr(
        hc,
        "_authority_snapshot",
        lambda: {
            "session_provider": "codex_cli",
        },
    )

    raw = """
    {
      "reply": "I found a possible improvement.",
      "improvement_observation": {
        "problem": "Conversation follow-up context can be clearer.",
        "evidence": "A repeated clarification was required.",
        "component": "mode6_session",
        "suggested_direction": "Retain better bounded context.",
        "source_mutation_required": false
      }
    }
    """

    result = hc.conversation_turn(
        "can this be improved?",
        responder=lambda _text, _context: raw,
    )

    assert result.reply == "I found a possible improvement."

    observation = result.improvement_observation

    assert observation is not None
    assert observation.evidence == (
        "A repeated clarification was required.",
    )
    assert observation.source_mutation_required is False


def test_reply_without_observation_remains_backward_compatible(
    monkeypatch,
):
    monkeypatch.setattr(
        hc,
        "_authority_snapshot",
        lambda: {
            "session_provider": "codex_cli",
        },
    )

    result = hc.conversation_turn(
        "hello",
        responder=lambda _text, _context: {
            "reply": "Hello.",
        },
    )

    assert result.reply == "Hello."
    assert result.improvement_observation is None


def test_malformed_observation_is_ignored_without_losing_reply(
    monkeypatch,
):
    monkeypatch.setattr(
        hc,
        "_authority_snapshot",
        lambda: {
            "session_provider": "codex_cli",
        },
    )

    result = hc.conversation_turn(
        "hello",
        responder=lambda _text, _context: {
            "reply": "Hello.",
            "improvement_observation": {
                "problem": "",
                "evidence": [],
                "component": "",
                "suggested_direction": "",
                "source_mutation_required": True,
            },
        },
    )

    assert result.reply == "Hello."
    assert result.improvement_observation is None


def test_provider_contract_allows_optional_observation_as_evidence(
    monkeypatch,
):
    captured = {}

    class FakeReasoner:
        def __call__(self, operation, payload):
            captured["operation"] = operation
            captured["payload"] = payload

            return {
                "reply": "I can continue normally.",
                "improvement_observation": _observation(),
            }

    monkeypatch.setattr(
        dpr,
        "SessionProviderReasoner",
        FakeReasoner,
    )

    result = hc.conversation_turn(
        "this behavior seems repetitive",
    )

    assert result.reply == "I can continue normally."
    assert result.improvement_observation is not None

    payload = captured["payload"]

    assert captured["operation"] == "conversation_reply"

    schema = payload["return_schema"]

    assert schema["reply"] == "string"
    assert "improvement_observation" in schema

    instructions = "\n".join(
        payload["instructions"]
    ).casefold()

    assert "improvement_observation" in instructions
    assert "optional" in instructions
    assert "evidence" in instructions

    assert (
        "does not grant mutation authority" in instructions
        or "no mutation authority" in instructions
    )


def test_observation_does_not_execute_rsi_or_change_authority(
    monkeypatch,
):
    calls = []

    authority = {
        "session_mode": "human_conversation",
        "session_provider": "codex_cli",
        "session_model": "codex-default",
    }

    monkeypatch.setattr(
        hc,
        "_authority_snapshot",
        lambda: dict(authority),
    )

    result = hc.conversation_turn(
        "I think this could be improved",
        responder=lambda _text, _context: {
            "reply": "I noticed a possible improvement.",
            "improvement_observation": _observation(),
        },
    )

    assert result.improvement_observation is not None
    assert result.authority == authority

    # Task 6 is observational only. There is deliberately no
    # callback/executor/RSI invocation surface on the result path.
    assert calls == []


def test_local_compact_fallback_remains_reply_only():
    prompt, system = dpr._mode6_candidate_request(
        provider_id="local_gguf",
        operation="conversation_reply",
        prompt="FULL",
        system_prompt="SYSTEM",
        context={
            "user_message": "hello",
            "return_schema": {
                "reply": "string",
                "improvement_observation": {
                    "problem": "string",
                },
            },
        },
    )

    assert '"reply":"string"' in prompt
    assert "improvement_observation" not in prompt
    assert system.endswith('Never claim file changes or actions.')
