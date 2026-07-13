"""OpenRouter provider plugin."""

from sophyane.providers.base import ProviderMetadata
from sophyane.providers.openai_compatible import (
    OpenAICompatibleProvider,
)


class OpenRouterProvider(OpenAICompatibleProvider):
    metadata = ProviderMetadata(
        provider_id="openrouter",
        display_name="OpenRouter",
        default_model="openai/gpt-4o-mini",
        environment_variable="OPENROUTER_API_KEY",
    )

    endpoint = "https://openrouter.ai/api/v1/chat/completions"
    extra_headers = {
        "HTTP-Referer": "https://github.com/badrpk/sophyane",
        "X-Title": "Sophyane",
    }
