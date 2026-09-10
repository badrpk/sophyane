from __future__ import annotations

from sophyane.context_builder import ContextPacket
from sophyane.providers.base import (
    Provider,
    ProviderCapabilities,
    ProviderMetadata,
)
from sophyane.providers.fallback import FallbackProvider


class RecordingProvider(Provider):
    metadata = ProviderMetadata(
        provider_id="recording",
        display_name="Recording",
        default_model="recording",
        environment_variable="",
        requires_api_key=False,
    )

    def __init__(
        self,
        *,
        capabilities: ProviderCapabilities,
        result: str = "OK",
        fail: bool = False,
    ) -> None:
        super().__init__(
            api_key="",
            model="recording",
            timeout=30,
            temperature=0.0,
            max_tokens=4096,
        )
        self._capabilities = capabilities
        self.result = result
        self.fail = fail
        self.prompts: list[str] = []

    def get_capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def generate(
        self,
        prompt: str,
        system_prompt: str,
    ) -> str:
        self.prompts.append(prompt)

        if self.fail:
            raise RuntimeError(
                "temporary network timeout"
            )

        return self.result


def make_packet() -> ContextPacket:
    packet = ContextPacket()

    packet.add(
        "Optional history:",
        "OPTIONAL_BEGIN_"
        + ("H" * 6000)
        + "_OPTIONAL_END",
        priority=10,
    )

    packet.add(
        "Immutable request:",
        "REQUEST_BEGIN_"
        + ("R" * 900)
        + "_REQUEST_END",
        priority=100,
        pinned=True,
    )

    return packet


def test_each_fallback_child_renders_from_same_original_packet():
    browser = RecordingProvider(
        capabilities=ProviderCapabilities(
            provider_managed_context=True,
            provider_managed_output=True,
        ),
        fail=True,
    )

    local = RecordingProvider(
        capabilities=ProviderCapabilities(
            context_window_tokens=1024,
            max_output_tokens=256,
        ),
        result="LOCAL_OK",
    )

    provider = FallbackProvider(
        [
            ("nifdu_browser", browser),
            ("local_gguf", local),
        ],
        primary="nifdu_browser",
    )

    packet = make_packet()
    original_items = tuple(packet.items)

    result = provider.generate_context(
        packet,
        "system",
    )

    assert result == "LOCAL_OK"
    assert provider.last_provider == "local_gguf"

    assert len(browser.prompts) == 1
    assert len(local.prompts) == 1

    browser_prompt = browser.prompts[0]
    local_prompt = local.prompts[0]

    # Provider-managed browser receives the complete packet.
    assert "OPTIONAL_BEGIN_" in browser_prompt
    assert "_OPTIONAL_END" in browser_prompt

    # Bounded local provider independently drops low-priority material.
    assert "OPTIONAL_BEGIN_" not in local_prompt
    assert "_OPTIONAL_END" not in local_prompt

    # Immutable request survives every rendering.
    for prompt in (
        browser_prompt,
        local_prompt,
    ):
        assert "REQUEST_BEGIN_" in prompt
        assert "_REQUEST_END" in prompt

    # Admission must not destructively modify the source packet.
    assert tuple(packet.items) == original_items


def test_legacy_generate_still_sends_identical_prompt_to_children():
    first = RecordingProvider(
        capabilities=ProviderCapabilities(
            context_window_tokens=512,
            max_output_tokens=128,
        ),
        fail=True,
    )

    second = RecordingProvider(
        capabilities=ProviderCapabilities(
            provider_managed_context=True,
        ),
        result="SECOND_OK",
    )

    provider = FallbackProvider(
        [
            ("first", first),
            ("second", second),
        ]
    )

    prompt = (
        "LEGACY_PROMPT_"
        + ("X" * 4000)
        + "_END"
    )

    assert provider.generate(
        prompt,
        "system",
    ) == "SECOND_OK"

    assert first.prompts == [prompt]
    assert second.prompts == [prompt]


def test_invalid_child_capabilities_do_not_break_context_generation():
    class InvalidCapabilityProvider(RecordingProvider):
        def get_capabilities(self):
            return {
                "context_window_tokens": 1,
            }

    child = InvalidCapabilityProvider(
        capabilities=ProviderCapabilities(),
    )

    provider = FallbackProvider(
        [("bad-capability", child)]
    )

    packet = make_packet()

    assert provider.generate_context(
        packet,
        "system",
    ) == "OK"

    # Conservative unknown capacity means no invented fixed truncation.
    assert "OPTIONAL_BEGIN_" in child.prompts[0]
    assert "_OPTIONAL_END" in child.prompts[0]
    assert "REQUEST_BEGIN_" in child.prompts[0]
    assert "_REQUEST_END" in child.prompts[0]


def test_bootstrap_path_uses_prompt_factory_source_contract():
    import inspect

    source = inspect.getsource(
        FallbackProvider.generate
    )

    # Dynamically bootstrapped rescue providers must not accidentally receive
    # the original primary-sized legacy prompt.
    assert "_prompt_factory(" in source
    assert "provider_id" in source
    assert "local" in source
