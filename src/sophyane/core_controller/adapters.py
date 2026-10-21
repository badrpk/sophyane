"""Small mode adapters that keep privileged work outside the controller."""

from __future__ import annotations

from .models import (
    ControllerContext,
    ControllerRequest,
    ExecutionResult,
    FailureBoundary,
    ModeName,
    ModePlan,
    ModeResult,
)
from .protocols import ModeAdapter


class DefaultModeAdapter:
    def __init__(self, mode: ModeName, *, provider_intent: str):
        self.mode = mode
        self.provider_intent = provider_intent

    def prepare(
        self,
        request: ControllerRequest,
        context: ControllerContext,
        *,
        trace_id: str,
    ) -> ModePlan:
        return ModePlan(
            trace_id=trace_id,
            mode=self.mode,
            provider_intent=self.provider_intent,
            requested_capabilities=tuple(
                str(item) for item in request.context.get("capabilities", ())
            ),
            payload={"text": request.text, "context": request.context, "state": context.state},
        )

    def interpret(self, plan: ModePlan, execution: ExecutionResult) -> ModeResult:
        if not execution.approved or not execution.completed:
            return ModeResult.failure(
                trace_id=plan.trace_id,
                mode=plan.mode,
                boundary=execution.failure_boundary or FailureBoundary.EXECUTION_DENIED,
                reason=execution.reason or "execution was not approved or completed",
            )
        return ModeResult(
            trace_id=plan.trace_id,
            mode=plan.mode,
            disposition="completed",
            output=execution.output,
            verification_status=execution.verification_status,
        )


class AdapterRegistry:
    def __init__(self, adapters: dict[ModeName, ModeAdapter] | None = None):
        self._adapters = dict(adapters or {})

    @classmethod
    def with_defaults(cls) -> "AdapterRegistry":
        intents = {
            ModeName.RACE: "race",
            ModeName.SLI_GRAPH: "sli_graph",
            ModeName.LOCAL_LLM: "local_gguf",
            ModeName.EXTERNAL_LLM: "codex_cli",
            ModeName.LEARNING: "learning",
            ModeName.HUMAN_CONVERSATION: "external_cascade",
        }
        return cls({mode: DefaultModeAdapter(mode, provider_intent=intent) for mode, intent in intents.items()})

    def register(self, mode: ModeName, adapter: ModeAdapter) -> None:
        if not isinstance(mode, ModeName):
            raise TypeError("mode must be a ModeName")
        if not isinstance(adapter, ModeAdapter):
            raise TypeError("adapter must implement ModeAdapter")
        self._adapters[mode] = adapter

    def get(self, mode: ModeName) -> ModeAdapter:
        try:
            return self._adapters[mode]
        except KeyError as error:
            raise KeyError(f"no adapter registered for {mode.value}") from error

    def modes(self) -> tuple[ModeName, ...]:
        return tuple(sorted(self._adapters, key=lambda item: item.value))
