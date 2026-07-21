from __future__ import annotations

from dataclasses import dataclass


def test_repeated_validator_repair_escalates_once(monkeypatch):
    from sophyane.providers import fallback
    from sophyane.runtime_quality_escalation import install_quality_escalation

    @dataclass
    class FakeProvider:
        name: str
        model: str
        replies: list[str]

        def generate(self, prompt: str, system_prompt: str) -> str:
            del prompt, system_prompt
            return self.replies.pop(0)

    local = FakeProvider("local_gguf", "qwen-local", ["bad-one", "bad-two", "local-resumed"])
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

    # Rescue is one-shot; normal work returns to the configured local model.
    assert provider.generate("Verify the corrected project locally.", "") == "bad-two"
    assert provider.last_provider == "local_gguf"


def test_local_order_includes_configured_rescue(monkeypatch):
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
