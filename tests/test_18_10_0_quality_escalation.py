from __future__ import annotations

import pytest

@pytest.fixture(scope="module", autouse=True)
def _restore_fallback_provider_class_after_module():
    """Keep quality-escalation runtime installation local to this module."""
    from sophyane.providers import fallback as _fallback

    cls = _fallback.FallbackProvider

    before_class = dict(
        cls.__dict__
    )

    sentinel_name = (
        "_quality_escalation_installed"
    )

    sentinel_existed = hasattr(
        _fallback,
        sentinel_name,
    )

    sentinel_before = getattr(
        _fallback,
        sentinel_name,
        None,
    )

    yield

    after_class = dict(
        cls.__dict__
    )

    changed_class_names = {
        name
        for name in (
            set(before_class)
            | set(after_class)
        )
        if (
            before_class.get(name)
            is not after_class.get(name)
        )
    }

    for name in changed_class_names:
        if name in before_class:
            setattr(
                cls,
                name,
                before_class[name],
            )
        else:
            delattr(
                cls,
                name,
            )

    if sentinel_existed:
        setattr(
            _fallback,
            sentinel_name,
            sentinel_before,
        )
    elif hasattr(
        _fallback,
        sentinel_name,
    ):
        delattr(
            _fallback,
            sentinel_name,
        )


from dataclasses import dataclass, field


def test_repeated_validator_repair_escalates_once(monkeypatch):
    from sophyane.providers import fallback
    from sophyane.runtime_quality_escalation import install_quality_escalation

    monkeypatch.setattr(
        fallback,
        "load_llm_config",
        lambda: {
            "active_provider": "local_gguf",
            "fallback_order": ["local_gguf", "gemini"],
            "allow_quality_escalation": True,
            "quality_rescue_provider": "gemini",
            "providers": {
                "local_gguf": {"enabled": True},
                "gemini": {"enabled": True},
            },
        },
    )

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
