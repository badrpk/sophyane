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


from dataclasses import dataclass


def test_cloud_rescue_owns_repair_sequence_until_nonrepair(monkeypatch):
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
        provider_id: str
        model: str
        replies: list[str]

        @property
        def metadata(self):
            return type("Metadata", (), {"provider_id": self.provider_id})()

        def generate(self, prompt: str, system_prompt: str) -> str:
            del system_prompt
            if self.provider_id == "gemini":
                assert "complete corrected artifact" in prompt
            return self.replies.pop(0)

    install_quality_escalation()
    local = FakeProvider("local_gguf", "qwen", ["local-1", "local-2", "local-next-task"])
    cloud = FakeProvider("gemini", "gemini-test", ["cloud-repair-1", "cloud-repair-2"])
    provider = fallback.FallbackProvider(
        [("local_gguf", local), ("gemini", cloud)],
        primary="local_gguf",
    )

    repair = "Repairing incomplete provider HTML: validation failed; return a corrected document."
    assert provider.generate(repair, "") == "local-1"
    assert provider.generate(repair, "") == "cloud-repair-1"
    assert provider.last_provider == "gemini"

    # A subsequent repair remains with the cloud expert instead of returning
    # prematurely to the weak local model.
    assert provider.generate(repair, "") == "cloud-repair-2"
    assert provider.last_provider == "gemini"

    # The first non-repair call ends the rescue sequence and resumes local-first.
    assert provider.generate("Start the next independent task.", "") == "local-2"
    assert provider.last_provider == "local_gguf"


def test_cloud_repair_prompt_requires_full_html():
    from sophyane.runtime_quality_escalation import _cloud_repair_prompt

    prompt = _cloud_repair_prompt("Validator failed: missing keyboard controls")
    assert "<!doctype html>" in prompt
    assert "complete self-contained HTML" in prompt
    assert "Do not use Markdown fences" in prompt
