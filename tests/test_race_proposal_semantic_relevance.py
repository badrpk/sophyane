from __future__ import annotations

from types import SimpleNamespace

import sophyane.race_orchestrator as orchestrator


OBJECTIVE = (
    "Parse incoming raw payload examples or rough functional descriptions, "
    "derive strict JSON schemas or OpenAPI specifications, and generate "
    "functional backend mocking stubs or test client scripts."
)


class _FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)

    def generate(self, user_prompt, system_prompt):
        assert self.responses
        return self.responses.pop(0)


def test_irrelevant_normalized_action_is_semantically_demoted(
    tmp_path,
    monkeypatch,
):
    provider = _FakeProvider(
        [
            '{"action":{"type":"run","command":"ls -la"}}',
            (
                '{"relevant":false,"score":0.08,'
                '"reason":"Directory listing does not materially implement '
                'schema derivation, OpenAPI generation, mocks, or clients."}'
            ),
        ]
    )

    monkeypatch.setattr(
        orchestrator,
        "_single_provider",
        lambda **kwargs: provider,
    )

    producer = orchestrator.make_provider_producer(
        engine="cloud",
        provider_id="gemini",
        request=OBJECTIVE,
        workspace=tmp_path,
        config={},
    )

    proposal = producer()

    assert proposal.kind == "action"
    assert proposal.payload["action"]["type"] == "run"
    assert proposal.payload["action"]["command"] == "ls -la"
    assert proposal.confidence == 0.08
    assert any(
        "semantic proposal relevance=irrelevant" in item
        for item in proposal.evidence
    )


def test_materially_relevant_action_receives_semantic_score(
    tmp_path,
    monkeypatch,
):
    provider = _FakeProvider(
        [
            (
                '{"action":{"type":"write_file","path":"api_harness.py",'
                '"content":"def infer_schema(payload):\\n    return {}\\n"}}'
            ),
            (
                '{"relevant":true,"score":0.91,'
                '"reason":"Creates a material implementation artifact for '
                'schema inference."}'
            ),
        ]
    )

    monkeypatch.setattr(
        orchestrator,
        "_single_provider",
        lambda **kwargs: provider,
    )

    producer = orchestrator.make_provider_producer(
        engine="cloud",
        provider_id="gemini",
        request=OBJECTIVE,
        workspace=tmp_path,
        config={},
    )

    proposal = producer()

    assert proposal.kind == "action"
    assert proposal.confidence == 0.91
    assert any(
        "semantic proposal relevance=relevant" in item
        for item in proposal.evidence
    )


def test_relevance_judge_outage_preserves_existing_proposal(
    tmp_path,
    monkeypatch,
):
    class Provider:
        calls = 0

        def generate(self, user_prompt, system_prompt):
            self.calls += 1

            if self.calls == 1:
                return '{"action":{"type":"run","command":"pytest -q"}}'

            raise RuntimeError("judge unavailable")

    provider = Provider()

    monkeypatch.setattr(
        orchestrator,
        "_single_provider",
        lambda **kwargs: provider,
    )

    producer = orchestrator.make_provider_producer(
        engine="cloud",
        provider_id="gemini",
        request="Repair the failing tests and verify the repository.",
        workspace=tmp_path,
        config={},
    )

    proposal = producer()

    # Availability failure must not masquerade as a semantic rejection.
    assert proposal.kind == "action"
    assert proposal.confidence == 0.82
    assert proposal.evidence == (
        "valid JSON",
        "execution action normalized by execution_runtime",
    )
