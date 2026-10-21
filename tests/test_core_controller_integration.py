from sophyane.cli_entry import build_core_controller
from sophyane.core_controller.adapters import AdapterRegistry
from sophyane.core_controller.models import (
    ControllerContext,
    ControllerRequest,
    ExecutionResult,
    ModeName,
    ProviderDecision,
)


class Gateway:
    def admit(self, plan):
        return ProviderDecision(plan.trace_id, plan.provider_intent, ready=True)


class Boundary:
    def execute(self, plan, decision):
        return ExecutionResult(True, True, output={"mode": plan.mode.value}, verification_status="verified")


def test_one_controller_entry_point_dispatches_all_six_modes(tmp_path):
    controller = build_core_controller(
        provider_gateway=Gateway(),
        execution_boundary=Boundary(),
        audit_path=tmp_path / "audit.jsonl",
    )
    context = ControllerContext(available_modes=tuple(ModeName))

    results = [
        controller.handle(ControllerRequest(text=mode.value, requested_mode=mode), context)
        for mode in ModeName
    ]

    assert [result.mode for result in results] == list(ModeName)
    assert all(result.disposition == "completed" for result in results)


def test_controller_can_be_constructed_with_a_custom_registry():
    registry = AdapterRegistry.with_defaults()
    controller = build_core_controller(
        adapter_registry=registry,
        provider_gateway=Gateway(),
        execution_boundary=Boundary(),
    )

    result = controller.handle(ControllerRequest(text="dry run", requested_mode=ModeName.LOCAL_LLM))

    assert result.disposition == "completed"


def test_default_entry_point_is_safe_and_does_not_execute_without_admission(tmp_path):
    controller = build_core_controller(audit_path=tmp_path / "audit.jsonl")

    result = controller.handle(
        ControllerRequest(text="attempt privileged action", requested_mode=ModeName.EXTERNAL_LLM)
    )

    assert result.disposition == "failed"
    assert result.failure_boundary.value == "provider_unavailable"
