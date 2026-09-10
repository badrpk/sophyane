from sophyane.providers.base import (
    Provider,
    ProviderCapabilities,
    ProviderMetadata,
)
from sophyane.providers.nifdu_browser import NifduBrowserProvider


class MinimalProvider(Provider):
    metadata = ProviderMetadata(
        provider_id="minimal",
        display_name="Minimal",
        default_model="minimal",
        environment_variable="",
        requires_api_key=False,
    )

    def generate(self, prompt: str, system_prompt: str) -> str:
        return "ok"


def test_unknown_provider_capabilities_are_conservative():
    provider = MinimalProvider(
        api_key="",
        model="minimal",
    )

    caps = provider.get_capabilities()

    assert caps.context_window_tokens is None
    assert caps.max_output_tokens is None
    assert caps.provider_managed_context is False
    assert caps.provider_managed_output is False


def test_nifdu_capacity_is_explicitly_browser_managed():
    provider = NifduBrowserProvider()

    caps = provider.get_capabilities()

    assert caps.context_window_tokens is None
    assert caps.max_output_tokens is None
    assert caps.provider_managed_context is True
    assert caps.provider_managed_output is True


def test_metadata_capabilities_are_backward_compatible():
    metadata = ProviderMetadata(
        provider_id="legacy",
        display_name="Legacy",
        default_model="legacy",
        environment_variable="LEGACY_KEY",
    )

    assert metadata.capabilities == ProviderCapabilities()
