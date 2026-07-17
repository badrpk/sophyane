"""Google Gemini provider plugin."""

from __future__ import annotations

import json

from sophyane.providers.base import (
    Provider,
    ProviderError,
    ProviderMetadata,
)
from sophyane.providers.http import post_json


class GeminiProvider(Provider):
    metadata = ProviderMetadata(
        provider_id="gemini",
        display_name="Google Gemini",
        default_model="gemini-2.5-flash",
        environment_variable="GEMINI_API_KEY",
    )

    def generate(
        self,
        prompt: str,
        system_prompt: str,
    ) -> str:
        # Match Google's current SDK authentication: keep credentials out of
        # URLs and send the API key using the x-goog-api-key header.
        model = self.model.strip()

        response = post_json(
            "https://generativelanguage.googleapis.com/"
            f"v1beta/models/{model}:generateContent",
            {
                "system_instruction": {
                    "parts": [{"text": system_prompt}],
                },
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": prompt}],
                    }
                ],
                "generationConfig": {
                    "temperature": self.temperature,
                    "maxOutputTokens": self.max_tokens,
                },
            },
            headers={"x-goog-api-key": self.api_key},
            timeout=self.timeout,
        )

        try:
            parts = response["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError(
                "Unexpected Gemini response: "
                f"{json.dumps(response)[:1000]}"
            ) from error

        texts = [
            item["text"]
            for item in parts
            if isinstance(item, dict)
            and isinstance(item.get("text"), str)
        ]

        if not texts:
            raise ProviderError("Gemini returned no text.")

        return "\n".join(texts).strip()
