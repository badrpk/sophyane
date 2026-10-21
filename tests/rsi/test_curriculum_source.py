from sophyane.rsi.curriculum import AbilityRecord
from sophyane.rsi.curriculum import CurriculumTask, ResourceClass, TaskSource
from sophyane.rsi.curriculum_proposals import ProposalResult
from sophyane.rsi.curriculum_source import CurriculumTaskSource


def context():
    return {
        "ability": AbilityRecord("a1", "first ability", ("verified",)),
        "allowed_paths": ("src/example.py",),
        "existing_task_ids": (),
        "capability_summary": "continue safely",
    }


class FakeAdapter:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def validate(self, raw, proposal_context):
        self.calls.append((raw, proposal_context))
        return self.result


def test_source_validates_one_llm_proposal():
    adapter = FakeAdapter(ProposalResult(True, reason="accepted"))
    calls = []
    source = CurriculumTaskSource(lambda prompt: calls.append(prompt) or '{"task_id":"t1"}', adapter)

    result = source.propose(context())

    assert result.accepted is True
    assert len(calls) == 1
    assert len(adapter.calls) == 1
    assert len(adapter.calls[0][0]) > 0
    assert '"verification_schema"' in calls[0]
    assert '"editable_paths_schema"' in calls[0]


def test_source_preserves_validator_rejection_for_malformed_output():
    adapter = FakeAdapter(ProposalResult(False, reason="invalid JSON proposal"))
    source = CurriculumTaskSource(lambda _prompt: "not-json", adapter)

    result = source.propose(context())

    assert result.accepted is False
    assert result.reason == "invalid JSON proposal"


def test_source_maps_provider_exception_without_retrying():
    calls = []

    def generate(_prompt):
        calls.append(True)
        raise OSError("provider offline")

    source = CurriculumTaskSource(generate, FakeAdapter(ProposalResult(True)))

    result = source.propose(context())

    assert result.accepted is False
    assert "provider" in result.reason
    assert len(calls) == 1


def test_source_truncates_prompt_and_calls_provider_once():
    prompts = []
    source = CurriculumTaskSource(lambda prompt: prompts.append(prompt) or "{}", FakeAdapter(ProposalResult(False, reason="rejected")))
    source.propose({**context(), "capability_summary": "x" * 50000})

    assert len(prompts) == 1
    assert len(prompts[0]) <= 12000


def test_source_routes_validated_proposal_through_intelligence_review():
    proposed = CurriculumTask("t1", "a1", "bounded", ("src/example.py",), ("pytest",), TaskSource.LLM_FOLLOW_UP, ResourceClass.LIGHT)
    adapter = FakeAdapter(ProposalResult(True, proposed, "accepted"))

    class Review:
        def review(self, proposal_context, proposal):
            assert proposal_context.ability.ability_id == "a1"
            return ProposalResult(True, proposal.task, "accepted", "local_llm", ("codex_cli",), "approved")

    result = CurriculumTaskSource(lambda _prompt: "{}", adapter, intelligence=Review()).propose(context())

    assert result.reviewers == ("codex_cli",)
    assert result.review_outcome == "approved"
