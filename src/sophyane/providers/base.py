"""Provider plugin interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class ProviderError(RuntimeError):
    """Raised for provider request or configuration failures."""


@dataclass(frozen=True)
class ProviderMetadata:
    provider_id: str
    display_name: str
    default_model: str
    environment_variable: str
    requires_api_key: bool = True


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

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_prompt: str,
    ) -> str:
        """Generate and return one text response."""
