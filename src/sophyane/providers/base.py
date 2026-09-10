"""Provider plugin interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class ProviderError(RuntimeError):
    """Raised for provider request or configuration failures."""


@dataclass(frozen=True)
class ProviderCapabilities:
    """Provider/model capacity information used by the Sophyane harness.

    ``None`` means Sophyane does not currently know a numeric limit.

    ``provider_managed_context`` means the external provider/session owns
    context-window admission and Sophyane must not invent a smaller fixed
    prompt ceiling.

    ``provider_managed_output`` means the external provider/session owns the
    generation ceiling and Sophyane must not infer one from the historical
    generic ``max_tokens`` setting.
    """

    context_window_tokens: int | None = None
    max_output_tokens: int | None = None
    provider_managed_context: bool = False
    provider_managed_output: bool = False


@dataclass(frozen=True)
class ProviderMetadata:
    provider_id: str
    display_name: str
    default_model: str
    environment_variable: str
    requires_api_key: bool = True
    capabilities: ProviderCapabilities = ProviderCapabilities()


class Provider(ABC):
    metadata: ProviderMetadata

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: int = 180,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens

    def get_capabilities(self) -> ProviderCapabilities:
        """Return effective capabilities for this provider instance.

        Providers with runtime-discovered/model-specific limits may override
        this method. The metadata value is intentionally conservative.
        """
        return self.metadata.capabilities

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_prompt: str,
    ) -> str:
        """Generate and return one text response."""
