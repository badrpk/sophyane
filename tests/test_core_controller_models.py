import json

import pytest

from sophyane.core_controller.models import (
    AuditEvent,
    ControllerContext,
    ControllerRequest,
    ExecutionResult,
    FailureBoundary,
    ModeName,
    ModePlan,
    ModeResult,
    ProviderDecision,
)


def test_mode_name_contains_the_six_architectural_modes():
    assert tuple(mode.value for mode in ModeName) == (
        "race", "sli_graph", "local_llm", "external_llm", "learning", "human_conversation",
    )


def test_request_is_bounded_and_serializes_deterministically():
    request = ControllerRequest(
        text="hello",
        caller_id="terminal",
        requested_mode=ModeName.LOCAL_LLM,
        session_id="session-1",
        context={"z": 2, "a": 1},
    )

    assert request.to_dict() == {
        "caller_id": "terminal",
        "context": {"a": 1, "z": 2},
        "requested_mode": "local_llm",
        "session_id": "session-1",
        "text": "hello",
    }
    assert json.dumps(request.to_dict(), sort_keys=True) == json.dumps(request.to_dict(), sort_keys=True)


def test_request_rejects_unbounded_text():
    with pytest.raises(ValueError, match="text"):
        ControllerRequest(text="x" * 10001)


def test_plan_and_provider_decision_are_serializable():
    plan = ModePlan(
        trace_id="trace-1",
        mode=ModeName.EXTERNAL_LLM,
        provider_intent="codex_cli",
        requested_capabilities=("read_repository",),
        payload={"request": "inspect"},
    )
    decision = ProviderDecision(
        trace_id="trace-1",
        provider="codex_cli",
        fallback_chain=("nifdu_browser", "local_gguf"),
        ready=True,
        reason="available",
    )
    assert plan.to_dict()["mode"] == "external_llm"
    assert decision.to_dict()["fallback_chain"] == ["nifdu_browser", "local_gguf"]


def test_failure_result_has_stable_boundary_and_audit_event():
    result = ModeResult.failure(
        trace_id="trace-2",
        mode=ModeName.LOCAL_LLM,
        boundary=FailureBoundary.EXECUTION_DENIED,
        reason="capability not admitted",
    )
    event = AuditEvent(
        trace_id="trace-2",
        event_type="terminal_failure",
        mode=ModeName.LOCAL_LLM,
        disposition=result.disposition,
        data={"reason": result.reason},
    )

    assert result.to_dict()["failure_boundary"] == "execution_denied"
    assert event.to_dict()["data"] == {"reason": "capability not admitted"}


def test_execution_result_requires_explicit_approval_state():
    result = ExecutionResult(
        approved=False,
        completed=False,
        output=None,
        verification_status="not_run",
        failure_boundary=FailureBoundary.EXECUTION_DENIED,
        reason="denied",
    )
    assert result.to_dict()["approved"] is False


def test_context_defaults_are_safe_and_serializable():
    context = ControllerContext()
    assert context.to_dict() == {"available_modes": [], "session_mode": None, "state": {}}
