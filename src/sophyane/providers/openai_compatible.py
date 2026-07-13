"""Reusable OpenAI-compatible provider implementation."""

from __future__ import annotations

import json

from sophyane.providers.base import (
    Provider,
    ProviderError,
    ProviderMetadata,
)
from sophyane.providers.http import post_json


class OpenAICompatibleProvider(Provider):
    endpoint = ""
    extra_headers: dict[str, str] = {}

    def generate(
        self,
        prompt: str,
        system_prompt: str,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            **self.extra_headers,
        }

        response = post_json(
            self.endpoint,
            {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            },
            headers=headers,
            timeout=self.timeout,
        )

        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError(
                "Unexpected response: "
                f"{json.dumps(response)[:1000]}"
            ) from error

        if not isinstance(content, str) or not content.strip():
            raise ProviderError("Provider returned no text.")

        return content.strip()
