from __future__ import annotations

import json


class FakeProvider:
    def __init__(
        self,
        result='{"hypotheses":[]}',
    ):
        self.result = result
        self.calls = []

    def generate(
        self,
        prompt,
        system_prompt,
    ):
        self.calls.append(
            (
                prompt,
                system_prompt,
            )
        )

        return self.result


def test_session_provider_reasoner_uses_one_cached_provider(
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

    provider = FakeProvider(
        '{"description":"candidate"}'
    )

    factories = {
        "calls": 0,
    }

    def factory():
        factories[
            "calls"
        ] += 1

        return provider

    reasoner = SessionProviderReasoner(
        provider_factory=factory,
    )

    first = reasoner(
        "generate_candidate",
        {
            "objective": "discover",
        },
    )

    second = reasoner(
        "generate_candidate",
        {
            "objective": "discover again",
        },
    )

    assert first
    assert second

    assert (
        factories[
            "calls"
        ]
        == 1
    )

    assert len(
        provider.calls
    ) == 2


def test_reasoner_prompt_contains_session_authority(
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

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODEL",
        "gemini-test",
    )

    provider = FakeProvider()

    reasoner = SessionProviderReasoner(
        provider_factory=lambda: provider,
    )

    # This test verifies authority metadata in the provider prompt, not the
    # generate_hypotheses semantic response contract. Use a generic discovery
    # operation so the fake provider response is not required to contain a
    # real hypothesis.
    reasoner(
        "inspect_authority_prompt",
        {
            "objective": (
                "improve episodic retrieval"
            )
        },
    )

    prompt, system = (
        provider.calls[0]
    )

    assert (
        "SOPHYANE_DISCOVERY_REASONING_REQUEST"
        in prompt
    )

    assert '"provider":"gemini"' in prompt

    assert (
        '"provider_switching_allowed":false'
        in prompt
    )

    assert (
        "Return one valid JSON object only."
        in system
    )


def test_sli_session_forbids_reasoner(
    monkeypatch,
):
    from sophyane.discovery_provider_reasoner import (
        SessionProviderReasoner,
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "sli_graph",
    )

    monkeypatch.delenv(
        "SOPHYANE_SESSION_PROVIDER",
        raising=False,
    )

    provider = FakeProvider()

    reasoner = SessionProviderReasoner(
        provider_factory=lambda: provider,
    )

    try:
        reasoner(
            "generate_hypotheses",
            {
                "objective": "x",
            },
        )
    except RuntimeError as exc:
        assert (
            "DISCOVERY_LLM_FORBIDDEN"
            in str(exc)
        )
    else:
        raise AssertionError(
            "SLI mode unexpectedly used LLM reasoner"
        )

    assert not provider.calls
