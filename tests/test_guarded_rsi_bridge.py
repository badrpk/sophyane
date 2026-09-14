from __future__ import annotations

import pytest

from sophyane.human_conversation import ImprovementObservation


def observation(**changes):
    values = {
        "problem": "Mode 6 loses the active context after a correction.",
        "evidence": ("The same correction was required twice.",),
        "component": "human_conversation",
        "suggested_direction": "Preserve bounded context across turns.",
        "source_mutation_required": True,
    }
    values.update(changes)
    return ImprovementObservation(**values)


def test_valid_observation_transforms_to_existing_rsi_weakness():
    from sophyane.mode6_rsi_executor import observation_to_weakness
    weakness = observation_to_weakness(observation(), baseline_commit="abc")
    assert weakness.description == observation().problem
    assert weakness.evidence == observation().evidence
    assert weakness.target_metric == "human_conversation"


@pytest.mark.parametrize("field", ["trusted", "instruction_authority", "mutation_authority"])
def test_authority_bearing_observation_fails_closed(field):
    from sophyane.mode6_rsi_executor import observation_to_weakness
    with pytest.raises(ValueError, match="authority"):
        observation_to_weakness(observation(**{field: True}), baseline_commit="abc")


@pytest.mark.parametrize("changes", [{"evidence": ()}, {"problem": ""}, {"component": ""}])
def test_empty_or_ungrounded_observation_fails_closed(changes):
    from sophyane.mode6_rsi_executor import observation_to_weakness
    with pytest.raises(ValueError):
        observation_to_weakness(observation(**changes), baseline_commit="abc")


def test_recording_observation_does_not_execute_source_mutation(monkeypatch):
    import sophyane.mode6_rsi_handoff as handoff
    monkeypatch.setattr(handoff.ledger, "propose_improvement", lambda *a, **k: {"ok": True})
    assert handoff.record_mode6_improvement_observation(observation())["handoff"] == "improvement_ledger_only"


def test_executable_rsi_requires_explicit_invocation():
    import sophyane.mode6_rsi_executor as executor
    assert hasattr(executor, "run_once_explicit")
