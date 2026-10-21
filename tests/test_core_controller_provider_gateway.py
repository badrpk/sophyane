from sophyane.core_controller.models import ModeName, ModePlan, ProviderPolicy
from sophyane.core_controller.provider_gateway import ConfiguredProviderGateway


def plan(mode, intent):
    return ModePlan("trace", mode, provider_intent=intent)


def test_local_only_rejects_external_provider_intent_before_readiness_probe():
    probes = []
    gateway = ConfiguredProviderGateway(
        policies={ModeName.LOCAL_LLM: ProviderPolicy(ModeName.LOCAL_LLM, "local_gguf")},
        readiness=lambda provider: probes.append(provider) or True,
    )

    decision = gateway.admit(plan(ModeName.LOCAL_LLM, "codex_cli"))

    assert decision.ready is False
    assert "local" in decision.reason
    assert probes == []


def test_external_sticky_prefers_selected_provider_and_declared_fallbacks():
    gateway = ConfiguredProviderGateway(
        policies={ModeName.EXTERNAL_LLM: ProviderPolicy(ModeName.EXTERNAL_LLM, "claude", ("nifdu_browser",))},
        readiness=lambda provider: provider == "claude",
    )

    decision = gateway.admit(plan(ModeName.EXTERNAL_LLM, "codex_cli"))

    assert decision.ready is True
    assert decision.provider == "claude"
    assert decision.fallback_chain == ("nifdu_browser",)


def test_mode6_uses_codex_then_nifdu_cascade():
    gateway = ConfiguredProviderGateway(
        policies={ModeName.HUMAN_CONVERSATION: ProviderPolicy(ModeName.HUMAN_CONVERSATION, "codex_cli", ("nifdu_browser",))},
        readiness=lambda provider: provider == "nifdu_browser",
    )

    decision = gateway.admit(plan(ModeName.HUMAN_CONVERSATION, "external_cascade"))

    assert decision.ready is True
    assert decision.provider == "nifdu_browser"
    assert "codex_cli unavailable" in decision.reason


def test_unavailable_policy_reports_without_provider_generation():
    calls = []
    gateway = ConfiguredProviderGateway(
        policies={ModeName.EXTERNAL_LLM: ProviderPolicy(ModeName.EXTERNAL_LLM, "codex_cli", ())},
        readiness=lambda provider: calls.append(provider) or False,
    )

    decision = gateway.admit(plan(ModeName.EXTERNAL_LLM, "codex_cli"))

    assert decision.ready is False
    assert decision.provider == "codex_cli"
    assert calls == ["codex_cli"]
