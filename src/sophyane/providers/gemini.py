"""Google Gemini provider plugin."""

from __future__ import annotations

import json
import urllib.parse

from sophyane.providers.base import (
    Provider,
    ProviderError,
    ProviderMetadata,
)
from sophyane.providers.http import post_json


PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "objective": {"type": "string"},
        "success_criteria": {"type": "array", "items": {"type": "string"}},
        "deterministic_checks": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": True},
        },
        "candidates": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": True},
        },
        "selected_index": {"type": "integer"},
        "selection_reason": {"type": "string"},
        "action": {"type": "object", "additionalProperties": True},
    },
    "required": [
        "objective",
        "success_criteria",
        "deterministic_checks",
        "candidates",
        "selected_index",
        "selection_reason",
        "action",
    ],
    "additionalProperties": False,
}


class GeminiProvider(Provider):
    metadata = ProviderMetadata(
        provider_id="gemini",
        display_name="Google Gemini",
        default_model="gemini-3.5-flash",
        environment_variable="GEMINI_API_KEY",
    )

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: int = 180,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            timeout=timeout,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self.generation_config = {
            "response_mime_type": "application/json",
            "response_schema": PLAN_SCHEMA,
        }
        self._token_usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "thinking_tokens": 0,
            "total_tokens": 0,
            "model_calls": 0,
        }

    def get_token_usage(self) -> dict[str, int]:
        return dict(self._token_usage)

    def _record_usage(self, response: dict) -> None:
        usage = response.get("usageMetadata")
        if not isinstance(usage, dict):
            return
        self._token_usage["input_tokens"] += int(usage.get("promptTokenCount", 0) or 0)
        self._token_usage["output_tokens"] += int(usage.get("candidatesTokenCount", 0) or 0)
        self._token_usage["thinking_tokens"] += int(usage.get("thoughtsTokenCount", 0) or 0)
        self._token_usage["total_tokens"] += int(usage.get("totalTokenCount", 0) or 0)
        self._token_usage["model_calls"] += 1

    def generate(self, prompt: str, system_prompt: str) -> str:
        model = urllib.parse.quote(self.model, safe="")
        key = urllib.parse.quote(self.api_key, safe="")
        response = post_json(
            "https://generativelanguage.googleapis.com/"
            f"v1beta/models/{model}:generateContent?key={key}",
            {
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": self.temperature,
                    "maxOutputTokens": self.max_tokens,
                    "responseMimeType": "application/json",
                    "responseJsonSchema": PLAN_SCHEMA,
                },
            },
            timeout=self.timeout,
        )
        self._record_usage(response)

        try:
            parts = response["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError(
                "Unexpected Gemini response: " f"{json.dumps(response)[:1000]}"
            ) from error

        texts = [
            item["text"]
            for item in parts
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ]
        if not texts:
            raise ProviderError("Gemini returned no text.")
        return "\n".join(texts).strip()
