"""Construction of concrete mode adapters with explicit readiness states."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .adapters import AdapterRegistry, ConcreteModeAdapter
from .models import ExecutionResult, FailureBoundary, ModeName, ModePlan, ProviderPolicy, ReadinessResult
from .provider_gateway import ConfiguredProviderGateway


class _ConcreteExecutionBoundary:
    """Run a mode handler only after provider admission has succeeded."""

    def execute_mode(self, plan, decision, adapter):
        return adapter.execute(
            plan,
            {"provider": decision.provider, "execution_approved": True},
        )

    def execute(self, plan, decision):
        return ExecutionResult(False, False, failure_boundary=FailureBoundary.EXECUTION_DENIED, reason="mode handler was not registered")


class _CallableHandler:
    def __init__(self, call: Callable[..., Any] | None, mode: ModeName):
        self.call = call
        self.mode = mode

    def execute(self, plan: ModePlan, capability: object) -> ExecutionResult:
        if self.call is None:
            return ExecutionResult(False, False, failure_boundary=FailureBoundary.PROVIDER_UNAVAILABLE, reason=f"{self.mode.value} handler unavailable")
        try:
            output = self.call(plan, capability)
        except Exception as error:
            return ExecutionResult(False, False, failure_boundary=FailureBoundary.CONTROLLER_INTERNAL, reason=str(error))
        return ExecutionResult(True, True, output=output, verification_status="verified")


class _Probe:
    def __init__(self, value: bool | Callable[[], bool], mode: ModeName):
        self.value = value
        self.mode = mode

    def check(self, _plan: ModePlan) -> ReadinessResult:
        try:
            ready = bool(self.value() if callable(self.value) else self.value)
        except Exception as error:
            return ReadinessResult(False, f"{self.mode.value} readiness error: {error}")
        return ReadinessResult(ready, "ready" if ready else f"{self.mode.value} dependency unavailable")


def build_live_registry(
    dependencies: Mapping[ModeName, Mapping[str, Any]] | None = None,
) -> tuple[AdapterRegistry, ConfiguredProviderGateway]:
    dependencies = dependencies or {}
    policies = {
        ModeName.RACE: ProviderPolicy(ModeName.RACE, "local_gguf"),
        ModeName.SLI_GRAPH: ProviderPolicy(ModeName.SLI_GRAPH, "local_gguf"),
        ModeName.LOCAL_LLM: ProviderPolicy(ModeName.LOCAL_LLM, "local_gguf"),
        ModeName.EXTERNAL_LLM: ProviderPolicy(ModeName.EXTERNAL_LLM, "codex_cli", ("nifdu_browser",)),
        ModeName.LEARNING: ProviderPolicy(ModeName.LEARNING, "local_gguf"),
        ModeName.HUMAN_CONVERSATION: ProviderPolicy(ModeName.HUMAN_CONVERSATION, "codex_cli", ("nifdu_browser",)),
    }
    provider_ready = {
        provider: any(
            bool(entry.get("ready", False))
            for entry in dependencies.values()
            if entry.get("provider", policies.get(ModeName.LOCAL_LLM).primary_provider) == provider
        )
        for provider in {policy.primary_provider for policy in policies.values()} | {
            fallback for policy in policies.values() for fallback in policy.permitted_fallbacks
        }
    }
    adapters = {}
    for mode, policy in policies.items():
        entry = dependencies.get(mode, {})
        adapters[mode] = ConcreteModeAdapter(
            mode,
            provider_intent=policy.primary_provider,
            handler=_CallableHandler(entry.get("handler"), mode),
            readiness=_Probe(entry.get("ready", False), mode),
            provider_policy=policy,
        )
    return AdapterRegistry(adapters), ConfiguredProviderGateway(
        policies=policies,
        readiness=lambda provider: provider_ready.get(provider, False),
    )
