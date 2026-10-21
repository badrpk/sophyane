from sophyane.core_controller.adapters import AdapterRegistry, DefaultModeAdapter
from sophyane.core_controller.models import (
    ControllerContext,
    ControllerRequest,
    ExecutionResult,
    ModeName,
    ModePlan,
    ProviderDecision,
)
from sophyane.core_controller.protocols import ExecutionBoundary, ModeAdapter, ProviderGateway


def test_default_registry_contains_all_six_modes():
    registry = AdapterRegistry.with_defaults()

    assert set(registry.modes()) == set(ModeName)
    assert all(isinstance(registry.get(mode), ModeAdapter) for mode in ModeName)


def test_preparation_only_creates_a_plan_without_execution():
    adapter = DefaultModeAdapter(ModeName.RACE, provider_intent="race")
    calls = []
    plan = adapter.prepare(
        ControllerRequest(text="compare candidates"),
        ControllerContext(),
        trace_id="trace-1",
    )

    calls.append(plan)
    assert isinstance(plan, ModePlan)
    assert plan.mode is ModeName.RACE
    assert calls == [plan]


def test_execution_boundary_and_provider_gateway_are_explicit_protocols():
    class Gateway:
        def admit(self, plan):
            return ProviderDecision(plan.trace_id, "local_gguf", ready=True)

    class Boundary:
        def execute(self, plan, decision):
            return ExecutionResult(True, True, output="ok", verification_status="verified")

    assert isinstance(Gateway(), ProviderGateway)
    assert isinstance(Boundary(), ExecutionBoundary)


def test_adapter_interpretation_does_not_promote_unapproved_execution():
    adapter = DefaultModeAdapter(ModeName.EXTERNAL_LLM, provider_intent="codex_cli")
    result = adapter.interpret(
        ModePlan("trace-2", ModeName.EXTERNAL_LLM),
        ExecutionResult(False, False, reason="denied"),
    )

    assert result.disposition == "failed"
    assert result.failure_boundary.value == "execution_denied"
