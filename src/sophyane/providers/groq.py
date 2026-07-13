"""Groq provider plugin."""

from sophyane.providers.base import ProviderMetadata
from sophyane.providers.openai_compatible import (
    OpenAICompatibleProvider,
)


class GroqProvider(OpenAICompatibleProvider):
    metadata = ProviderMetadata(
        provider_id="groq",
        display_name="Groq",
        default_model="llama-3.3-70b-versatile",
        environment_variable="GROQ_API_KEY",
    )

    endpoint = "https://api.groq.com/openai/v1/chat/completions"
