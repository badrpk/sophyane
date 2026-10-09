import json

from sophyane import human_conversation as hc
from sophyane.discovery_provider_reasoner import (
    SessionProviderReasoner,
    _operation_response_usable,
    _semantic_repair_prompt,
)


def test_conversation_reply_without_semantic_disposition_is_not_usable():
    assert (
        _operation_response_usable(
            "conversation_reply",
            '{"reply":"I can inspect the repository."}',
        )
        is False
    )


def test_conversation_reply_requires_supported_semantic_disposition():
    assert (
        _operation_response_usable(
            "conversation_reply",
            (
                '{"reply":"Proceeding.",'
                '"semantic_disposition":"actionable_mission"}'
            ),
        )
        is True
    )

    assert (
        _operation_response_usable(
            "conversation_reply",
            (
                '{"reply":"Hello.",'
                '"semantic_disposition":"conversation"}'
            ),
        )
        is True
    )

    assert (
        _operation_response_usable(
            "conversation_reply",
            (
                '{"reply":"Need more information.",'
                '"semantic_disposition":"clarification"}'
            ),
        )
        is True
    )


def test_conversation_reply_rejects_unknown_semantic_disposition():
    assert (
        _operation_response_usable(
            "conversation_reply",
            (
                '{"reply":"Proceeding.",'
                '"semantic_disposition":"invented_state"}'
            ),
        )
        is False
    )


def test_conversation_reply_repair_prompt_requires_semantic_disposition():
    repaired = _semantic_repair_prompt(
        operation="conversation_reply",
        original_prompt="ORIGINAL",
        invalid_response='{"reply":"reply only"}',
    )

    assert '"reply"' in repaired
    assert '"semantic_disposition"' in repaired
    assert "actionable_mission" in repaired


def test_missing_disposition_is_repaired_before_reasoner_returns():
    class FakeProvider:
        provider_id = "offline_regression"

        def __init__(self):
            self.calls = []

        def generate(self, prompt, system_prompt, **kwargs):
            self.calls.append((prompt, system_prompt, kwargs))

            if len(self.calls) == 1:
                return json.dumps(
                    {
                        "reply": (
                            "I can inspect the repository and run the tests."
                        )
                    }
                )

            return json.dumps(
                {
                    "reply": "Proceeding through guarded execution.",
                    "semantic_disposition": "actionable_mission",
                }
            )

    provider = FakeProvider()

    result = SessionProviderReasoner._generate_response(
        provider,
        "conversation_reply",
        (
            "Inspect the existing repository, run all tests, "
            "and report actual command output and exit codes."
        ),
        "system",
        "",
    )

    assert len(provider.calls) == 2
    assert (
        hc._extract_semantic_disposition(result)
        == "actionable_mission"
    )


def test_valid_actionable_response_does_not_trigger_repair():
    class FakeProvider:
        provider_id = "offline_regression"

        def __init__(self):
            self.calls = 0

        def generate(self, prompt, system_prompt, **kwargs):
            self.calls += 1

            return json.dumps(
                {
                    "reply": "Proceeding through guarded execution.",
                    "semantic_disposition": "actionable_mission",
                }
            )

    provider = FakeProvider()

    result = SessionProviderReasoner._generate_response(
        provider,
        "conversation_reply",
        "Inspect the repository and run the tests.",
        "system",
        "",
    )

    assert provider.calls == 1
    assert (
        hc._extract_semantic_disposition(result)
        == "actionable_mission"
    )
