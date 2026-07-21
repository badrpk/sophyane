from __future__ import annotations

from dataclasses import dataclass


def test_cloud_rescue_owns_repair_sequence_until_nonrepair():
    from sophyane.providers import fallback
    from sophyane.runtime_quality_escalation import install_quality_escalation

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
