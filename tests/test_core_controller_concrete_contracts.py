import pytest

from sophyane.core_controller.adapters import ConcreteModeAdapter
from sophyane.core_controller.models import (
    ControllerContext,
    ControllerRequest,
    ExecutionResult,
    FailureBoundary,
    ModeName,
    ModePlan,
    ProviderPolicy,
    ReadinessResult,
)
from sophyane.core_controller.protocols import ModeHandler, ReadinessProbe


def plan(mode=ModeName.LOCAL_LLM):
    return ModePlan("trace", mode, provider_intent="local_gguf", payload={"text": "hello"})


def test_handler_and_readiness_protocols_are_explicit():
    class Handler:
        def execute(self, _plan, _capability):
            return ExecutionResult(True, True, output="ok")

    class Probe:
        def check(self, _plan):
            return ReadinessResult(True, "ready")

    assert isinstance(Handler(), ModeHandler)
    assert isinstance(Probe(), ReadinessProbe)


def test_concrete_adapter_invokes_handler_only_after_ready_probe():
    calls = []

    class Handler:
        def execute(self, received_plan, capability):
            calls.append((received_plan, capability))
            return ExecutionResult(True, True, output="bounded")

    class Probe:
        def check(self, _plan):
            return ReadinessResult(True, "ready")

    adapter = ConcreteModeAdapter(
        ModeName.LOCAL_LLM,
        provider_intent="local_gguf",
        handler=Handler(),
        readiness=Probe(),
        provider_policy=ProviderPolicy(ModeName.LOCAL_LLM, "local_gguf", ()),
    )
    result = adapter.execute(plan(), capability={"approved": True})

    assert result.output == "bounded"
    assert calls == [(plan(), {"approved": True})]


def test_unready_adapter_returns_structured_failure_without_handler_call():
    class Handler:
        def execute(self, _plan, _capability):
            raise AssertionError("handler must not run")

    class Probe:
        def check(self, _plan):
            return ReadinessResult(False, "llama server unavailable")

    adapter = ConcreteModeAdapter(
        ModeName.LOCAL_LLM,
        provider_intent="local_gguf",
        handler=Handler(),
        readiness=Probe(),
        provider_policy=ProviderPolicy(ModeName.LOCAL_LLM, "local_gguf", ()),
    )
    result = adapter.execute(plan(), capability={})

    assert result.failure_boundary is FailureBoundary.PROVIDER_UNAVAILABLE
    assert "unavailable" in result.reason


def test_execution_output_is_bounded():
    class Handler:
        def execute(self, _plan, _capability):
            return ExecutionResult(True, True, output="x" * 20000)

    class Probe:
        def check(self, _plan):
            return ReadinessResult(True, "ready")

    adapter = ConcreteModeAdapter(
        ModeName.LOCAL_LLM,
        provider_intent="local_gguf",
        handler=Handler(),
        readiness=Probe(),
        provider_policy=ProviderPolicy(ModeName.LOCAL_LLM, "local_gguf", ()),
    )
    with pytest.raises(ValueError, match="output"):
        adapter.execute(plan(), capability={})


def test_provider_policy_is_mode_specific():
    policy = ProviderPolicy(ModeName.HUMAN_CONVERSATION, "codex_cli", ("nifdu_browser",))

    assert policy.mode is ModeName.HUMAN_CONVERSATION
    assert policy.primary_provider == "codex_cli"
    assert policy.permitted_fallbacks == ("nifdu_browser",)
