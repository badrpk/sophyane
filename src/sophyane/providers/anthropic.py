"""Anthropic Claude provider plugin."""

from __future__ import annotations

import json

from sophyane.providers.base import (
    Provider,
    ProviderError,
    ProviderMetadata,
)
from sophyane.providers.http import post_json


class AnthropicProvider(Provider):
    metadata = ProviderMetadata(
        provider_id="anthropic",
        display_name="Anthropic Claude",
        default_model="claude-sonnet-4-20250514",
        environment_variable="ANTHROPIC_API_KEY",
    )

    def generate(
        self,
        prompt: str,
        system_prompt: str,
    ) -> str:
        response = post_json(
            "https://api.anthropic.com/v1/messages",
            {
                "model": self.model,
                "system": system_prompt,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            },
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            timeout=self.timeout,
        )

        texts = [
            item["text"]
            for item in response.get("content", [])
            if isinstance(item, dict)
            and item.get("type") == "text"
            and isinstance(item.get("text"), str)
        ]

        if not texts:
            raise ProviderError(
                "Anthropic returned no text: "
                f"{json.dumps(response)[:1000]}"
            )

        return "\n".join(texts).strip()
