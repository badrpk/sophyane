from sophyane.core_controller.adapters import AdapterRegistry
from sophyane.core_controller.controller import CoreController
from sophyane.core_controller.models import (
    ControllerContext,
    ControllerRequest,
    ExecutionResult,
    FailureBoundary,
    ModeName,
    ProviderDecision,
)


class Audit:
    def __init__(self):
        self.events = []

    def append(self, event):
        self.events.append(event)


class BrokenAudit:
    def append(self, event):
        raise OSError("audit storage unavailable")


class Gateway:
    def __init__(self, decision):
        self.decision = decision
        self.plans = []

    def admit(self, plan):
        self.plans.append(plan)
        return self.decision


class Boundary:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def execute(self, plan, decision):
        self.calls.append((plan, decision))
        return self.result


def controller(gateway, boundary, audit=None):
    return CoreController(
        adapter_registry=AdapterRegistry.with_defaults(),
        provider_gateway=gateway,
        execution_boundary=boundary,
        audit_store=audit or Audit(),
    )


def request(mode=ModeName.LOCAL_LLM):
    return ControllerRequest(text="do bounded work", requested_mode=mode)


def context():
    return ControllerContext(available_modes=tuple(ModeName))


def test_dry_run_lifecycle_audits_and_returns_completed_result():
    audit = Audit()
    gateway = Gateway(ProviderDecision("trace", "local_gguf", ready=True))
    boundary = Boundary(ExecutionResult(True, True, output="plan", verification_status="not_run"))

    result = controller(gateway, boundary, audit).handle(request(), context())

    assert result.disposition == "completed"
    assert len(gateway.plans) == 1
    assert len(boundary.calls) == 1
    assert [event.event_type for event in audit.events] == [
        "mode_selected", "provider_admitted", "execution_completed",
    ]


def test_provider_denial_never_reaches_execution_boundary():
    audit = Audit()
    boundary = Boundary(ExecutionResult(True, True, output="unsafe"))
    result = controller(
        Gateway(ProviderDecision("trace", "local_gguf", ready=False, reason="offline")),
        boundary,
        audit,
    ).handle(request(), context())

    assert result.failure_boundary is FailureBoundary.PROVIDER_UNAVAILABLE
    assert boundary.calls == []


def test_execution_denial_is_returned_without_success():
    result = controller(
        Gateway(ProviderDecision("trace", "local_gguf", ready=True)),
        Boundary(ExecutionResult(False, False, failure_boundary=FailureBoundary.EXECUTION_DENIED, reason="policy")),
    ).handle(request(), context())

    assert result.failure_boundary is FailureBoundary.EXECUTION_DENIED


def test_verification_failure_is_not_promoted():
    result = controller(
        Gateway(ProviderDecision("trace", "local_gguf", ready=True)),
        Boundary(ExecutionResult(True, True, output="candidate", verification_status="failed")),
    ).handle(request(), context())

    assert result.failure_boundary is FailureBoundary.VERIFICATION_FAILED


def test_model_cannot_self_promote_without_independent_approval():
    result = controller(
        Gateway(ProviderDecision("trace", "local_gguf", ready=True)),
        Boundary(ExecutionResult(True, True, output="candidate", verification_status="promoted")),
    ).handle(request(), context())

    assert result.failure_boundary is FailureBoundary.PROMOTION_DENIED


def test_provider_fallback_stays_inside_the_selected_plan():
    gateway = Gateway(ProviderDecision("trace", "local_gguf", fallback_chain=("nifdu_browser",), ready=True))
    boundary = Boundary(ExecutionResult(True, True, output="ok"))
    controller(gateway, boundary).handle(request(ModeName.LOCAL_LLM), context())

    assert gateway.plans[0].mode is ModeName.LOCAL_LLM
    assert gateway.plans[0].provider_intent == "local_gguf"


def test_audit_storage_failure_fails_closed_with_state_boundary():
    result = CoreController(
        adapter_registry=AdapterRegistry.with_defaults(),
        provider_gateway=Gateway(ProviderDecision("trace", "local_gguf", ready=True)),
        execution_boundary=Boundary(ExecutionResult(True, True, output="must not be trusted")),
        audit_store=BrokenAudit(),
    ).handle(request(), context())

    assert result.failure_boundary is FailureBoundary.STATE_UNAVAILABLE
    assert result.disposition == "failed"
