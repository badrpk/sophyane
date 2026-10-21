"""Dependency-injection protocols for controller adapters and authority gates."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import (
    ControllerContext,
    ControllerRequest,
    ExecutionResult,
    ModePlan,
    ModeResult,
    ProviderDecision,
    ReadinessResult,
)


@runtime_checkable
class ModeAdapter(Protocol):
    def prepare(
        self,
        request: ControllerRequest,
        context: ControllerContext,
        *,
        trace_id: str,
    ) -> ModePlan: ...

    def interpret(self, plan: ModePlan, execution: ExecutionResult) -> ModeResult: ...


@runtime_checkable
class ProviderGateway(Protocol):
    def admit(self, plan: ModePlan) -> ProviderDecision: ...


@runtime_checkable
class ExecutionBoundary(Protocol):
    def execute(self, plan: ModePlan, decision: ProviderDecision) -> ExecutionResult: ...


@runtime_checkable
class ModeHandler(Protocol):
    def execute(self, plan: ModePlan, capability: object) -> ExecutionResult: ...


@runtime_checkable
class ReadinessProbe(Protocol):
    def check(self, plan: ModePlan) -> ReadinessResult: ...
