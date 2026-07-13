"""OpenAI provider plugin."""

from __future__ import annotations

import json

from sophyane.providers.base import (
    Provider,
    ProviderError,
    ProviderMetadata,
)
from sophyane.providers.http import post_json


class OpenAIProvider(Provider):
    metadata = ProviderMetadata(
        provider_id="openai",
        display_name="OpenAI",
        default_model="gpt-5-mini",
        environment_variable="OPENAI_API_KEY",
    )

    def generate(
        self,
        prompt: str,
        system_prompt: str,
    ) -> str:
        response = post_json(
            "https://api.openai.com/v1/responses",
            {
                "model": self.model,
                "instructions": system_prompt,
                "input": prompt,
                "max_output_tokens": self.max_tokens,
            },
            headers={
                "Authorization": f"Bearer {self.api_key}",
            },
            timeout=self.timeout,
        )

        output_text = response.get("output_text")

        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        collected: list[str] = []

        for output_item in response.get("output", []):
            if not isinstance(output_item, dict):
                continue

            for part in output_item.get("content", []):
                if not isinstance(part, dict):
                    continue

                text = part.get("text")

                if isinstance(text, str):
                    collected.append(text)

        if collected:
            return "\n".join(collected).strip()

        raise ProviderError(
            f"OpenAI returned no text: {json.dumps(response)[:1000]}"
        )
