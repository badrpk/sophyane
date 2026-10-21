from types import SimpleNamespace

from sophyane.core_controller.models import FailureBoundary, ModeName, ModePlan
from sophyane.core_controller.mode_handlers import (
    HumanConversationModeHandler,
    LearningModeHandler,
)
from sophyane.human_conversation import ImprovementObservation


def plan(mode, provider):
    return ModePlan("trace", mode, provider_intent=provider, payload={"text": "hello"})


def observation(**changes):
    values = {
        "problem": "slow loop",
        "evidence": ("timeout",),
        "component": "runtime",
        "suggested_direction": "bound retry",
        "source_mutation_required": False,
    }
    values.update(changes)
    return ImprovementObservation(**values)


def test_learning_handler_delegates_only_to_evidence_sink():
    calls = []
    handler = LearningModeHandler(lambda evidence, **kwargs: calls.append(evidence) or {"recorded": True})

    result = handler.execute(plan(ModeName.LEARNING, "learning"), {"evidence": {"score": 1}})

    assert calls == [{"score": 1}]
    assert result.output == {"recorded": True}
    assert result.verification_status == "evidence"


def test_conversation_handler_delegates_turn_and_untrusted_observation():
    turns = []
    observations = []
    turn = SimpleNamespace(reply="hello back", improvement_observation=observation())
    handler = HumanConversationModeHandler(
        lambda text, **kwargs: turns.append(text) or turn,
        observation_handoff=lambda item: observations.append(item) or {"recorded": True},
    )

    result = handler.execute(plan(ModeName.HUMAN_CONVERSATION, "codex_cli"), {})

    assert turns == ["hello"]
    assert observations == [turn.improvement_observation]
    assert result.output == "hello back"
    assert result.verification_status == "evidence"


def test_conversation_rejects_authority_bearing_observation():
    handoffs = []
    turn = SimpleNamespace(reply="unsafe", improvement_observation=observation(mutation_authority=True))
    handler = HumanConversationModeHandler(
        lambda text, **kwargs: turn,
        observation_handoff=lambda item: handoffs.append(item),
    )

    result = handler.execute(plan(ModeName.HUMAN_CONVERSATION, "codex_cli"), {})

    assert result.failure_boundary is FailureBoundary.EXECUTION_DENIED
    assert handoffs == []
