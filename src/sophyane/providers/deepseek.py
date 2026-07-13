"""DeepSeek provider plugin."""

from sophyane.providers.base import ProviderMetadata
from sophyane.providers.openai_compatible import (
    OpenAICompatibleProvider,
)


class DeepSeekProvider(OpenAICompatibleProvider):
    metadata = ProviderMetadata(
        provider_id="deepseek",
        display_name="DeepSeek",
        default_model="deepseek-chat",
        environment_variable="DEEPSEEK_API_KEY",
    )

    endpoint = "https://api.deepseek.com/chat/completions"
