"""xAI Grok provider plugin."""

from sophyane.providers.base import ProviderMetadata
from sophyane.providers.openai_compatible import (
    OpenAICompatibleProvider,
)


class XAIProvider(OpenAICompatibleProvider):
    metadata = ProviderMetadata(
        provider_id="xai",
        display_name="xAI Grok",
        default_model="grok-4",
        environment_variable="XAI_API_KEY",
    )

    endpoint = "https://api.x.ai/v1/chat/completions"
