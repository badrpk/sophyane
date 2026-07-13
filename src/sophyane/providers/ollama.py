"""Local Ollama provider plugin."""

from __future__ import annotations

import json

from sophyane.providers.base import (
    Provider,
    ProviderError,
    ProviderMetadata,
)
from sophyane.providers.http import post_json


class OllamaProvider(Provider):
    metadata = ProviderMetadata(
        provider_id="ollama",
        display_name="Ollama (local)",
        default_model="llama3.2",
        environment_variable="",
        requires_api_key=False,
    )

    def generate(
        self,
        prompt: str,
        system_prompt: str,
    ) -> str:
        response = post_json(
            "http://127.0.0.1:11434/api/chat",
            {
                "model": self.model,
                "stream": False,
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
                "options": {
                    "temperature": self.temperature,
                },
            },
            timeout=self.timeout,
        )

        try:
            content = response["message"]["content"]
        except (KeyError, TypeError) as error:
            raise ProviderError(
                "Unexpected Ollama response: "
                f"{json.dumps(response)[:1000]}"
            ) from error

        if not isinstance(content, str) or not content.strip():
            raise ProviderError("Ollama returned no text.")

        return content.strip()
