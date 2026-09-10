from sophyane.providers.base import (
    Provider,
    ProviderCapabilities,
    ProviderMetadata,
)
from sophyane.providers.fallback import FallbackProvider


class CapabilityProvider(Provider):
    metadata = ProviderMetadata(
        provider_id="capability",
        display_name="Capability",
        default_model="capability",
        environment_variable="",
        requires_api_key=False,
    )

    def __init__(
        self,
        *,
        capabilities: ProviderCapabilities,
        result: str = "ok",
        fail: bool = False,
    ) -> None:
        super().__init__(
            api_key="",
            model="capability",
            timeout=30,
            temperature=0.0,
            max_tokens=4096,
        )
        self._capabilities = capabilities
        self.result = result
        self.fail = fail

    def get_capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def generate(self, prompt: str, system_prompt: str) -> str:
        if self.fail:
            raise RuntimeError("synthetic failure")
        return self.result


def test_fallback_reports_primary_capabilities_before_generation():
    primary_caps = ProviderCapabilities(
        provider_managed_context=True,
        provider_managed_output=True,
    )
    fallback_caps = ProviderCapabilities(
        context_window_tokens=8192,
        max_output_tokens=2048,
    )

    primary = CapabilityProvider(
        capabilities=primary_caps,
    )
    fallback = CapabilityProvider(
        capabilities=fallback_caps,
    )

    provider = FallbackProvider(
        [
            ("nifdu_browser", primary),
            ("local_gguf", fallback),
        ],
        primary="nifdu_browser",
    )

    assert provider.last_provider == ""
    assert provider.get_capabilities() == primary_caps


def test_fallback_reports_provider_that_actually_succeeded():
    first_caps = ProviderCapabilities(
        provider_managed_context=True,
        provider_managed_output=True,
    )
    second_caps = ProviderCapabilities(
        context_window_tokens=32768,
        max_output_tokens=8192,
    )

    first = CapabilityProvider(
        capabilities=first_caps,
        fail=True,
    )
    second = CapabilityProvider(
        capabilities=second_caps,
        result="fallback-ok",
    )

    provider = FallbackProvider(
        [
            ("nifdu_browser", first),
            ("api_provider", second),
        ],
        primary="nifdu_browser",
    )

    assert provider.generate(
        "prompt",
        "system",
    ) == "fallback-ok"

    assert provider.last_provider == "api_provider"
    assert provider.get_capabilities() == second_caps


def test_fallback_does_not_merge_child_limits():
    browser_caps = ProviderCapabilities(
        provider_managed_context=True,
        provider_managed_output=True,
    )
    local_caps = ProviderCapabilities(
        context_window_tokens=2048,
        max_output_tokens=1024,
    )

    provider = FallbackProvider(
        [
            (
                "browser",
                CapabilityProvider(
                    capabilities=browser_caps,
                ),
            ),
            (
                "local",
                CapabilityProvider(
                    capabilities=local_caps,
                ),
            ),
        ],
        primary="browser",
    )

    assert provider.get_capabilities() == browser_caps
    assert provider.get_capabilities() != local_caps


def test_unknown_primary_identity_is_conservative():
    child = CapabilityProvider(
        capabilities=ProviderCapabilities(
            context_window_tokens=99999,
            max_output_tokens=99999,
        ),
    )

    provider = FallbackProvider(
        [("child", child)],
        primary="missing-provider",
    )

    assert provider.get_capabilities() == ProviderCapabilities()


def test_invalid_child_capabilities_are_conservative():
    class BadProvider(CapabilityProvider):
        def get_capabilities(self):
            return {"context_window_tokens": 100000}

    provider = FallbackProvider(
        [
            (
                "bad",
                BadProvider(
                    capabilities=ProviderCapabilities(),
                ),
            )
        ],
        primary="bad",
    )

    assert provider.get_capabilities() == ProviderCapabilities()
