from sophyane.core_controller.models import FailureBoundary, ModeName, ModePlan
from sophyane.core_controller.mode_handlers import (
    ExternalLlmModeHandler,
    LocalLlmModeHandler,
    RaceModeHandler,
    SliGraphModeHandler,
)


def plan(mode, provider):
    return ModePlan("trace", mode, provider_intent=provider, payload={"text": "task"})


def test_race_handler_delegates_and_never_marks_candidate_promoted():
    calls = []
    handler = RaceModeHandler(lambda request, **kwargs: calls.append((request, kwargs)) or {"winner": "candidate"})

    result = handler.execute(plan(ModeName.RACE, "race"), {"execution_approved": True})

    assert calls[0][0] == "task"
    assert result.completed is True
    assert result.verification_status == "candidate"
    assert result.promotion_approved is False


def test_sli_handler_delegates_to_injected_planner():
    calls = []
    handler = SliGraphModeHandler(lambda request, **kwargs: calls.append(request) or {"plan": "bounded"})

    result = handler.execute(plan(ModeName.SLI_GRAPH, "sli_graph"), {})

    assert calls == ["task"]
    assert result.output == {"plan": "bounded"}


def test_local_handler_rejects_external_provider_decision():
    calls = []
    handler = LocalLlmModeHandler(lambda request, **kwargs: calls.append(request) or "local")

    result = handler.execute(
        plan(ModeName.LOCAL_LLM, "local_gguf"),
        {"provider": "codex_cli", "execution_approved": True},
    )

    assert result.failure_boundary is FailureBoundary.PROVIDER_UNAVAILABLE
    assert calls == []


def test_external_handler_uses_selected_provider_and_does_not_self_promote():
    calls = []
    handler = ExternalLlmModeHandler(lambda request, provider, **kwargs: calls.append((request, provider)) or "answer")

    result = handler.execute(
        plan(ModeName.EXTERNAL_LLM, "codex_cli"),
        {"provider": "nifdu_browser", "execution_approved": True},
    )

    assert calls == [("task", "nifdu_browser")]
    assert result.output == "answer"
    assert result.promotion_approved is False
