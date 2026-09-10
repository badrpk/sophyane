from __future__ import annotations

import json


class RecordingProvider:
    def __init__(self):
        self.calls = []

    def generate(
        self,
        prompt,
        system_prompt,
        *args,
        **kwargs,
    ):
        self.calls.append(
            (
                prompt,
                system_prompt,
            )
        )

        return json.dumps(
            {
                "hypotheses": [
                    {
                        "statement": (
                            "Penalizing candidates after "
                            "recorded failures reduces "
                            "repeat failed selections."
                        ),
                        "rationale": (
                            "Static ranking preserves the "
                            "same ordering after failure."
                        ),
                        "predictions": [
                            (
                                "A deterministic synthetic "
                                "benchmark selects fewer "
                                "previously failed candidates."
                            )
                        ],
                        "assumptions": [
                            (
                                "Failure history is available "
                                "to the reranker."
                            )
                        ],
                    }
                ]
            }
        )


def test_local_hypothesis_generation_uses_compact_prompt(
    monkeypatch,
):
    from sophyane.discovery_provider_reasoner import (
        SessionProviderReasoner,
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "local_llm",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_PROVIDER",
        "local_gguf",
    )

    provider = RecordingProvider()

    reasoner = SessionProviderReasoner(
        provider_factory=lambda: provider,
    )

    result = reasoner(
        "generate_hypotheses",
        {
            "objective": (
                "Reduce repeated failed candidate "
                "selection."
            ),
            "requirements": {
                "maximum": 1,
            },
            "knowledge": [
                {
                    "source": "one",
                    "kind": "history",
                    "score": 1.0,
                    "content": "x" * 5000,
                },
                {
                    "source": "two",
                    "kind": "history",
                    "score": 0.9,
                    "content": "y" * 5000,
                },
                {
                    "source": "three",
                    "kind": "history",
                    "score": 0.8,
                    "content": "z" * 5000,
                },
            ],
            "return_schema": {
                "hypotheses": [
                    {
                        "statement": "string",
                        "rationale": "string",
                        "predictions": [
                            "string",
                        ],
                        "assumptions": [
                            "string",
                        ],
                    }
                ]
            },
        },
    )

    assert result

    assert len(
        provider.calls
    ) == 1

    prompt, system = (
        provider.calls[0]
    )

    assert (
        "SOPHYANE_DISCOVERY_LOCAL_COMPACT_REQUEST"
        in prompt
    )

    assert (
        "SOPHYANE_DISCOVERY_REASONING_REQUEST"
        not in prompt
    )

    assert len(prompt) < 4000

    assert (
        '"provider_switching_allowed":false'
        in prompt
    )

    assert (
        "exactly one non-empty hypothesis"
        in system
    )

    assert (
        "Do not rename hypotheses to candidates."
        in system
    )


def test_cloud_hypothesis_generation_keeps_normal_prompt(
    monkeypatch,
):
    from sophyane.discovery_provider_reasoner import (
        SessionProviderReasoner,
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "cloud_llm",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_PROVIDER",
        "gemini",
    )

    provider = RecordingProvider()

    reasoner = SessionProviderReasoner(
        provider_factory=lambda: provider,
    )

    reasoner(
        "generate_hypotheses",
        {
            "objective": "test",
            "return_schema": {
                "hypotheses": [
                    {
                        "statement": "string",
                    }
                ]
            },
        },
    )

    prompt, system = (
        provider.calls[0]
    )

    assert (
        "SOPHYANE_DISCOVERY_REASONING_REQUEST"
        in prompt
    )

    assert (
        "SOPHYANE_DISCOVERY_LOCAL_COMPACT_REQUEST"
        not in prompt
    )

    assert (
        "Return one valid JSON object only."
        in system
    )


def test_local_non_hypothesis_operation_is_not_compacted(
    monkeypatch,
):
    from sophyane.discovery_provider_reasoner import (
        SessionProviderReasoner,
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "local_llm",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_PROVIDER",
        "local_gguf",
    )

    provider = RecordingProvider()

    reasoner = SessionProviderReasoner(
        provider_factory=lambda: provider,
    )

    reasoner(
        "inspect_authority_prompt",
        {
            "objective": "test",
        },
    )

    prompt, _ = (
        provider.calls[0]
    )

    assert (
        "SOPHYANE_DISCOVERY_REASONING_REQUEST"
        in prompt
    )

    assert (
        "SOPHYANE_DISCOVERY_LOCAL_COMPACT_REQUEST"
        not in prompt
    )
