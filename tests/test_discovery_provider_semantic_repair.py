from __future__ import annotations

import json

import pytest

from sophyane.discovery_provider_reasoner import (
    SessionProviderReasoner,
    _operation_response_usable,
)


class FakeProvider:
    def __init__(
        self,
        responses,
    ):
        self.responses = list(
            responses
        )
        self.calls = []

    def generate(
        self,
        prompt,
        system_prompt,
        *args,
        **kwargs,
    ):
        self.calls.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "args": args,
                "kwargs": kwargs,
            }
        )

        if not self.responses:
            raise AssertionError(
                "unexpected provider call"
            )

        return self.responses.pop(
            0
        )


def context():
    return {
        "objective": (
            "reduce repeated failed selection"
        ),
        "requirements": {
            "maximum": 1,
        },
        "return_schema": {
            "hypotheses": [
                {
                    "statement": "string",
                    "rationale": "string",
                    "predictions": [
                        "string"
                    ],
                    "assumptions": [
                        "string"
                    ],
                }
            ]
        },
    }


def test_operation_response_usable_rejects_empty_hypotheses():
    assert (
        _operation_response_usable(
            "generate_hypotheses",
            json.dumps(
                {
                    "hypotheses": [],
                }
            ),
        )
        is False
    )


def test_operation_response_usable_accepts_statement():
    assert (
        _operation_response_usable(
            "generate_hypotheses",
            json.dumps(
                {
                    "hypotheses": [
                        {
                            "statement": (
                                "penalize known failures"
                            )
                        }
                    ],
                }
            ),
        )
        is True
    )


def test_empty_candidates_trigger_same_provider_repair(
    monkeypatch,
):
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "cloud_llm",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_PROVIDER",
        "gemini",
    )

    provider = FakeProvider(
        [
            json.dumps(
                {
                    "candidates": [],
                    "selected_index": 0,
                    "selection_reason": (
                        "candidate selected"
                    ),
                }
            ),
            json.dumps(
                {
                    "hypotheses": [
                        {
                            "statement": (
                                "Penalizing candidates "
                                "after verified failures "
                                "reduces repeated failed "
                                "selection."
                            ),
                            "rationale": (
                                "Static ranking ignores "
                                "execution outcome."
                            ),
                            "predictions": [
                                (
                                    "repeat failures "
                                    "decrease"
                                )
                            ],
                            "assumptions": [
                                (
                                    "failure history "
                                    "is available"
                                )
                            ],
                        }
                    ]
                }
            ),
        ]
    )

    reasoner = SessionProviderReasoner(
        provider_factory=lambda: provider,
    )

    result = reasoner(
        "generate_hypotheses",
        context(),
    )

    parsed = json.loads(
        result
    )

    assert len(
        parsed["hypotheses"]
    ) == 1

    assert len(
        provider.calls
    ) == 2

    assert (
        "SOPHYANE_DISCOVERY_SCHEMA_REPAIR_REQUEST"
        in provider.calls[1]["prompt"]
    )

    assert (
        '"hypotheses"'
        in provider.calls[1]["prompt"]
    )


def test_valid_first_response_does_not_retry(
    monkeypatch,
):
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "cloud_llm",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_PROVIDER",
        "gemini",
    )

    provider = FakeProvider(
        [
            json.dumps(
                {
                    "hypotheses": [
                        {
                            "statement": (
                                "valid hypothesis"
                            )
                        }
                    ]
                }
            ),
        ]
    )

    reasoner = SessionProviderReasoner(
        provider_factory=lambda: provider,
    )

    result = reasoner(
        "generate_hypotheses",
        context(),
    )

    parsed = json.loads(
        result
    )

    assert (
        parsed["hypotheses"][0][
            "statement"
        ]
        == "valid hypothesis"
    )

    assert len(
        provider.calls
    ) == 1


def test_failed_repair_becomes_explicit_schema_error(
    monkeypatch,
):
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "cloud_llm",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_PROVIDER",
        "gemini",
    )

    provider = FakeProvider(
        [
            json.dumps(
                {
                    "candidates": [],
                }
            ),
            json.dumps(
                {
                    "hypotheses": [],
                }
            ),
        ]
    )

    reasoner = SessionProviderReasoner(
        provider_factory=lambda: provider,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "DISCOVERY_PROVIDER_SCHEMA_VIOLATION:"
            "generate_hypotheses:"
            "REPAIR_FAILED"
        ),
    ):
        reasoner(
            "generate_hypotheses",
            context(),
        )

    assert len(
        provider.calls
    ) == 2


def test_conversation_reply_repair_prompt_requires_reply_json():
    from sophyane.discovery_provider_reasoner import (
        _semantic_repair_prompt,
    )

    original = (
        "SOPHYANE_DISCOVERY_REASONING_REQUEST\n"
        '{"return_schema":{"reply":"string"}}'
    )

    repaired = _semantic_repair_prompt(
        operation="conversation_reply",
        original_prompt=original,
        invalid_response=(
            "I will modify the requested file now."
        ),
    )

    assert repaired != original
    assert "SOPHYANE_DISCOVERY_SCHEMA_REPAIR_REQUEST" in repaired
    assert "conversation_reply" in repaired
    assert '"reply"' in repaired
    assert "exactly one JSON object" in repaired
    assert "I will modify the requested file now." in repaired


def test_conversation_reply_usable_requires_reply_field():
    from sophyane.discovery_provider_reasoner import (
        _operation_response_usable,
    )

    assert (
        _operation_response_usable(
            "conversation_reply",
            '{"action":{"type":"respond","text":"hello"}}',
        )
        is False
    )


def test_conversation_reply_usable_rejects_empty_reply():
    from sophyane.discovery_provider_reasoner import (
        _operation_response_usable,
    )

    assert (
        _operation_response_usable(
            "conversation_reply",
            '{"reply":""}',
        )
        is False
    )

    assert (
        _operation_response_usable(
            "conversation_reply",
            '{"reply":"   "}',
        )
        is False
    )


def test_conversation_reply_usable_accepts_nonempty_reply():
    from sophyane.discovery_provider_reasoner import (
        _operation_response_usable,
    )

    assert (
        _operation_response_usable(
            "conversation_reply",
            '{"reply":"Hello."}',
        )
        is True
    )
