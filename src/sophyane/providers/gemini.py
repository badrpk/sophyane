"""Google Gemini provider plugin."""

from __future__ import annotations

import json
import os
import urllib.parse
from typing import Any

from sophyane.providers.base import (
    Provider,
    ProviderError,
    ProviderMetadata,
)
from sophyane.providers.http import post_json
from sophyane.generation_contract import parse_generation_request


PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "objective": {"type": "string"},
        "success_criteria": {
            "type": "array",
            "items": {"type": "string"},
        },
        "deterministic_checks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": True,
            },
        },
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": True,
            },
        },
        "selected_index": {"type": "integer"},
        "selection_reason": {"type": "string"},
        "action": {
            "type": "object",
            "additionalProperties": True,
        },
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


# These phrases are emitted by Sophyane's browser artifact and continuation
# paths. Such calls must return raw source, never a JSON planning envelope.
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

        # Retained for compatibility with code inspecting this attribute.
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

        self.last_finish_reason = "unknown"
        self.last_response_metadata: dict[str, Any] = {}
        self.last_generation_mode = "structured"

    def get_token_usage(self) -> dict[str, int]:
        return dict(self._token_usage)

    def _record_usage(self, response: dict[str, Any]) -> None:
        usage = response.get("usageMetadata")
        if isinstance(usage, dict):
            self._token_usage["input_tokens"] += int(
                usage.get("promptTokenCount", 0) or 0
            )
            self._token_usage["output_tokens"] += int(
                usage.get("candidatesTokenCount", 0) or 0
            )
            self._token_usage["thinking_tokens"] += int(
                usage.get("thoughtsTokenCount", 0) or 0
            )
            self._token_usage["total_tokens"] += int(
                usage.get("totalTokenCount", 0) or 0
            )

        self._token_usage["model_calls"] += 1

    def _record_metadata(self, response: dict[str, Any]) -> None:
        self.last_finish_reason = "unknown"

        candidates = response.get("candidates")
        if isinstance(candidates, list) and candidates:
            candidate = candidates[0]
            if isinstance(candidate, dict):
                reason = (
                    candidate.get("finishReason")
                    or candidate.get("finish_reason")
                )
                if reason:
                    self.last_finish_reason = str(reason)

        self.last_response_metadata = {
            "finish_reason": self.last_finish_reason,
            "usage": response.get("usageMetadata", {}),
            "prompt_feedback": response.get("promptFeedback", {}),
            "generation_mode": self.last_generation_mode,
        }

    def _generation_config(
        self,
        *,
        raw_mode: bool,
    ) -> dict[str, Any]:
        if not raw_mode:
            # Planning/action mode remains deterministic and schema-bound.
            return {
                "temperature": self.temperature,
                "maxOutputTokens": min(
                    self.max_tokens,
                    int(os.environ.get(
                        "SOPHYANE_GEMINI_PLAN_MAX_TOKENS",
                        "3072",
                    )),
                ),
                "responseMimeType": "application/json",
                "responseJsonSchema": PLAN_SCHEMA,
            }

        # Artifact mode returns literal source code. A JSON schema would force
        # the complete document into an escaped JSON string and cause severe
        # latency, truncation, and continuation failures.
        raw_temperature = float(
            os.environ.get(
                "SOPHYANE_GEMINI_RAW_TEMPERATURE",
                "0.2",
            )
        )
        thinking_budget = int(
            os.environ.get(
                "SOPHYANE_GEMINI_RAW_THINKING_BUDGET",
                "0",
            )
        )

        config: dict[str, Any] = {
            "temperature": raw_temperature,
            "maxOutputTokens": self.max_tokens,
            "responseMimeType": "text/plain",
        }

        # HTML completion is a direct generation task. Disabling thinking
        # prevents hidden reasoning from consuming latency and token budget.
        config["thinkingConfig"] = {
            "thinkingBudget": thinking_budget,
        }
        return config

    def generate(
        self,
        prompt: str,
        system_prompt: str,
    ) -> str:
        model = urllib.parse.quote(self.model, safe="")
        key = urllib.parse.quote(self.api_key, safe="")

        request = parse_generation_request(prompt)
        prompt = request.prompt
        raw_mode = request.mode == "raw_artifact"
        self.last_generation_mode = request.mode

        response = post_json(
            "https://generativelanguage.googleapis.com/"
            f"v1beta/models/{model}:generateContent?key={key}",
            {
                "system_instruction": {
                    "parts": [{"text": system_prompt}]
                },
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": prompt}],
                    }
                ],
                "generationConfig": self._generation_config(
                    raw_mode=raw_mode
                ),
            },
            timeout=self.timeout,
        )

        if not isinstance(response, dict):
            raise ProviderError(
                "Gemini returned a non-object response."
            )

        self._record_usage(response)
        self._record_metadata(response)

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
            raise ProviderError(
                "Gemini returned no text "
                f"(finish reason: {self.last_finish_reason})."
            )

        return "\n".join(texts).strip()
