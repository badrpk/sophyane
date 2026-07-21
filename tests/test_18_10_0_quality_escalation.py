from __future__ import annotations

from dataclasses import dataclass, field


def test_repeated_validator_repair_escalates_once():
    from sophyane.providers import fallback
    from sophyane.runtime_quality_escalation import install_quality_escalation

    @dataclass
    class FakeProvider:
        name: str
        model: str
        replies: list[str]
        timeout: int = 60
        temperature: float = 0.2
        max_tokens: int = 2048
        calls: list[str] = field(default_factory=list)

        def generate(self, prompt: str, system_prompt: str) -> str:
            del system_prompt
            self.calls.append(prompt)
            return self.replies.pop(0)

    local = FakeProvider(
        "local_gguf",
        "qwen-local",
        ["bad-one", "local-resumed"],
    )
    cloud = FakeProvider("gemini", "gemini-test", ["expert-repair"])

    install_quality_escalation()
    provider = fallback.FallbackProvider(
        [("local_gguf", local), ("gemini", cloud)],
        primary="local_gguf",
    )

    repair = (
        "Repairing incomplete provider HTML. Previous HTML validation failed: "
        "snake game has no keyboard or touch controls. Return a corrected document."
    )

    assert provider.generate(repair, "") == "bad-one"
    assert provider.generate(repair, "") == "expert-repair"
    assert provider.last_provider == "gemini"
    assert len(cloud.calls) == 1

    # Rescue is one-shot; normal work returns to the configured local model.
    assert provider.generate("Verify the corrected project locally.", "") == "local-resumed"
    assert provider.last_provider == "local_gguf"
    assert len(local.calls) == 2


def test_local_order_includes_configured_rescue():
    from sophyane.providers import fallback
    from sophyane.runtime_quality_escalation import install_quality_escalation

    install_quality_escalation()
    order = fallback.resolve_provider_order(
        "local_gguf",
        llm_config={
            "allow_quality_escalation": True,
            "quality_rescue_provider": "gemini",
            "fallback_order": ["gemini", "openai"],
        },
    )

    assert order[0] == "local_gguf"
    assert "gemini" in order
    assert "openai" in order
    assert order.count("gemini") == 1


def test_quality_escalation_can_be_disabled():
    from sophyane.providers import fallback
    from sophyane.runtime_quality_escalation import install_quality_escalation

    install_quality_escalation()
    order = fallback.resolve_provider_order(
        "local_gguf",
        llm_config={
            "allow_quality_escalation": False,
            "fallback_order": ["gemini"],
        },
    )

    assert order == ["local_gguf"]
