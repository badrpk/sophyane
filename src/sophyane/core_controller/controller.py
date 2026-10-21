"""Authoritative request lifecycle for Sophyane's six modes."""

from __future__ import annotations

import uuid
from typing import Callable, Protocol

from .adapters import AdapterRegistry
from .failures import boundary_for
from .models import (
    AuditEvent,
    ControllerContext,
    ControllerRequest,
    ExecutionResult,
    FailureBoundary,
    ModeName,
    ModeResult,
    ProviderDecision,
)
from .protocols import ExecutionBoundary, ProviderGateway
from .selection import ModeSelection, select_mode


class AuditStore(Protocol):
    def append(self, event: AuditEvent) -> None: ...


class CoreController:
    def __init__(
        self,
        *,
        adapter_registry: AdapterRegistry,
        provider_gateway: ProviderGateway,
        execution_boundary: ExecutionBoundary,
        audit_store: AuditStore,
        mode_selector: Callable[..., ModeSelection] = select_mode,
    ):
        self.adapter_registry = adapter_registry
        self.provider_gateway = provider_gateway
        self.execution_boundary = execution_boundary
        self.audit_store = audit_store
        self.mode_selector = mode_selector

    def readiness(self) -> dict[str, object]:
        return {"modes": self.adapter_registry.readiness()}

    def handle(
        self,
        request: ControllerRequest,
        context: ControllerContext | None = None,
    ) -> ModeResult:
        context = context or ControllerContext()
        trace_id = uuid.uuid4().hex
        try:
            selection = self.mode_selector(request, context)
            mode = selection.mode
            self._audit(AuditEvent(trace_id, "mode_selected", mode, "selected", {"source": selection.source}))
        except Exception as error:
            if isinstance(error, OSError):
                return self._state_failure(trace_id, request.requested_mode or ModeName.HUMAN_CONVERSATION, str(error))
            mode = request.requested_mode or ModeName.HUMAN_CONVERSATION
            return self._failure(trace_id, mode, boundary_for(error, phase="selection"), str(error))

        try:
            adapter = self.adapter_registry.get(mode)
            plan = adapter.prepare(request, context, trace_id=trace_id)
            decision = self.provider_gateway.admit(plan)
        except Exception as error:
            return self._failure(trace_id, mode, boundary_for(error, phase="provider"), str(error))
        if not decision.ready:
            return self._failure(trace_id, mode, FailureBoundary.PROVIDER_UNAVAILABLE, decision.reason or "provider unavailable")
        try:
            self._audit(AuditEvent(trace_id, "provider_admitted", mode, "admitted", {"provider": decision.provider}))
        except Exception as error:
            return self._state_failure(trace_id, mode, str(error))

        try:
            execution = self.execution_boundary.execute(plan, decision)
        except Exception as error:
            return self._failure(trace_id, mode, boundary_for(error, phase="execution"), str(error))
        if not execution.approved or not execution.completed:
            boundary = execution.failure_boundary or FailureBoundary.EXECUTION_DENIED
            return self._failure(trace_id, mode, boundary, execution.reason or "execution denied")
        if execution.verification_status == "failed":
            return self._failure(trace_id, mode, FailureBoundary.VERIFICATION_FAILED, execution.reason or "verification failed")
        if execution.verification_status == "promoted" and not execution.promotion_approved:
            return self._failure(trace_id, mode, FailureBoundary.PROMOTION_DENIED, "independent promotion approval is required")
        result = adapter.interpret(plan, execution)
        try:
            self._audit(AuditEvent(trace_id, "execution_completed", mode, result.disposition, {"verification": result.verification_status}))
        except Exception as error:
            return self._state_failure(trace_id, mode, str(error))
        return result

    def _failure(self, trace_id: str, mode: ModeName, boundary: FailureBoundary, reason: str) -> ModeResult:
        result = ModeResult.failure(trace_id=trace_id, mode=mode, boundary=boundary, reason=reason[:1000])
        try:
            self._audit(AuditEvent(trace_id, "terminal_failure", mode, result.disposition, {"boundary": boundary, "reason": result.reason}))
            return result
        except Exception as error:
            return self._state_failure(trace_id, mode, str(error))

    def _state_failure(self, trace_id: str, mode: ModeName, reason: str) -> ModeResult:
        return ModeResult.failure(
            trace_id=trace_id,
            mode=mode,
            boundary=FailureBoundary.STATE_UNAVAILABLE,
            reason=f"audit storage unavailable: {reason}"[:1000],
        )

    def _audit(self, event: AuditEvent) -> None:
        self.audit_store.append(event)
