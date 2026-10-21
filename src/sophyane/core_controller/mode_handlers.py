"""Concrete adapters for the existing Race, SLI, Local, and External paths."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .models import ExecutionResult, FailureBoundary, ModePlan


def _capability_value(capability: object, key: str, default: Any = None) -> Any:
    return capability.get(key, default) if isinstance(capability, Mapping) else default


def _invoke(call: Callable[..., Any], plan: ModePlan, capability: object, **extra: Any) -> ExecutionResult:
    if not _capability_value(capability, "execution_approved", True):
        return ExecutionResult(False, False, failure_boundary=FailureBoundary.EXECUTION_DENIED, reason="execution not approved")
    try:
        output = call(plan.payload.get("text", ""), plan=plan, capability=capability, **extra)
    except Exception as error:
        return ExecutionResult(False, False, failure_boundary=FailureBoundary.CONTROLLER_INTERNAL, reason=str(error))
    return ExecutionResult(True, True, output=output, verification_status="verified")


class RaceModeHandler:
    def __init__(self, run_race: Callable[..., Any]):
        self.run_race = run_race

    def execute(self, plan: ModePlan, capability: object) -> ExecutionResult:
        result = _invoke(self.run_race, plan, capability)
        if result.completed:
            return ExecutionResult(
                result.approved,
                result.completed,
                output=result.output,
                verification_status="candidate",
                promotion_approved=False,
            )
        return result


class SliGraphModeHandler:
    def __init__(self, plan_with_sli: Callable[..., Any]):
        self.plan_with_sli = plan_with_sli

    def execute(self, plan: ModePlan, capability: object) -> ExecutionResult:
        return _invoke(self.plan_with_sli, plan, capability)


class LocalLlmModeHandler:
    def __init__(self, run_local: Callable[..., Any]):
        self.run_local = run_local

    def execute(self, plan: ModePlan, capability: object) -> ExecutionResult:
        provider = _capability_value(capability, "provider", plan.provider_intent)
        if provider != "local_gguf":
            return ExecutionResult(
                False,
                False,
                failure_boundary=FailureBoundary.PROVIDER_UNAVAILABLE,
                reason="local mode rejects external provider decision",
            )
        return _invoke(self.run_local, plan, capability, provider=provider)


class ExternalLlmModeHandler:
    def __init__(self, run_external: Callable[..., Any]):
        self.run_external = run_external

    def execute(self, plan: ModePlan, capability: object) -> ExecutionResult:
        provider = _capability_value(capability, "provider", plan.provider_intent)
        return _invoke(self.run_external, plan, capability, provider=provider)
