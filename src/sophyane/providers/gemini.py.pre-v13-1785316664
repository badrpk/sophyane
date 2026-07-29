"""Google Gemini provider plugin."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from sophyane.providers.base import (
    Provider,
    ProviderError,
    ProviderMetadata,
)
from sophyane.providers.http import post_json
from sophyane.version import __version__


ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "object",
            "additionalProperties": True,
            "description": "One executable Sophyane action.",
        },
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": True,
            },
        },
    },
    "additionalProperties": True,
}

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
        "files": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
    },
    "required": ["objective"],
    "additionalProperties": True,
}


class GeminiProvider(Provider):
    metadata = ProviderMetadata(
        provider_id="gemini",
        display_name="Google Gemini",
        default_model="gemini-3.6-flash",
        environment_variable="GEMINI_API_KEY",
    )

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: int = 180,
        temperature: float = 0.3,
        max_tokens: int = 0,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            timeout=timeout,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._model_output_limit: int | None = None
        self._token_usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "thinking_tokens": 0,
            "total_tokens": 0,
            "model_calls": 0,
        }

    def get_token_usage(self) -> dict[str, int]:
        return dict(self._token_usage)

    def _record_usage(self, response: dict[str, Any]) -> None:
        usage = response.get("usageMetadata")
        if not isinstance(usage, dict):
            return
        self._token_usage["input_tokens"] += int(usage.get("promptTokenCount", 0) or 0)
        self._token_usage["output_tokens"] += int(usage.get("candidatesTokenCount", 0) or 0)
        self._token_usage["thinking_tokens"] += int(usage.get("thoughtsTokenCount", 0) or 0)
        self._token_usage["total_tokens"] += int(usage.get("totalTokenCount", 0) or 0)
        self._token_usage["model_calls"] += 1

    def _maximum_output_tokens(self) -> int:
        """Read the active model's real outputTokenLimit from Gemini."""
        if self._model_output_limit is not None:
            return self._model_output_limit

        model = urllib.parse.quote(self.model, safe="")
        key = urllib.parse.quote(self.api_key, safe="")
        request = urllib.request.Request(
            "https://generativelanguage.googleapis.com/"
            f"v1beta/models/{model}?key={key}",
            headers={"User-Agent": f"Sophyane/{__version__}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=min(self.timeout, 30)) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
            limit = int(payload.get("outputTokenLimit", 0) or 0)
        except (OSError, ValueError, TypeError, json.JSONDecodeError, urllib.error.URLError):
            limit = 0

        self._model_output_limit = limit if limit > 0 else 65536
        return self._model_output_limit

    @staticmethod
    def _response_mode(prompt: str, system_prompt: str) -> str:
        """Classify the call as raw source, executable action JSON, or planning JSON."""
        text = " ".join(f"{system_prompt}\n{prompt}".lower().split())

        raw_markers = (
            "output raw html only",
            "raw html",
            "beginning <!doctype html>",
            "ending </html>",
            "complete self-contained index.html",
            "self-contained index.html",
            "continue the unfinished index.html",
            "output only missing javascript/html",
            "one-shot provider-generated html",
            "provider-generated html artifact",
            "return source code only",
            "output source code only",
            "no json, markdown",
        )
        if any(marker in text for marker in raw_markers):
            return "raw"

        action_markers = (
            "compact provider repair",
            "adaptive execution artifact request",
            "return exactly one valid json object",
            "return one compact json object",
            "top-level action",
            "write_file",
            "append_file",
            "run_command",
            "files array",
            '"files"',
            "artifact request",
        )
        if any(marker in text for marker in action_markers):
            return "action"
        return "plan"

    @staticmethod
    def _candidate_parts(response: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            parts = response["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError):
            return []
        return [item for item in parts if isinstance(item, dict)]

    @classmethod
    def _extract_text(cls, response: dict[str, Any]) -> str | None:
        texts = [
            item["text"]
            for item in cls._candidate_parts(response)
            if isinstance(item.get("text"), str)
        ]
        value = "\n".join(texts).strip()
        return value or None

    @classmethod
    def _contains_function_call(cls, response: dict[str, Any]) -> bool:
        return any(isinstance(item.get("functionCall"), dict) for item in cls._candidate_parts(response))

    def generate(self, prompt: str, system_prompt: str) -> str:
        model = urllib.parse.quote(self.model, safe="")
        key = urllib.parse.quote(self.api_key, safe="")
        mode = self._response_mode(prompt, system_prompt)
        output_limit = self._maximum_output_tokens()

        generation_config: dict[str, Any] = {
            "temperature": self.temperature,
            "maxOutputTokens": output_limit,
        }
        if mode != "raw":
            generation_config.update(
                {
                    "responseMimeType": "application/json",
                    "responseJsonSchema": ACTION_SCHEMA if mode == "action" else PLAN_SCHEMA,
                }
            )

        payload: dict[str, Any] = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": generation_config,
            # Sophyane owns tool execution. Gemini must return text/source/JSON
            # rather than invoking native or inherited function declarations.
            "toolConfig": {"functionCallingConfig": {"mode": "NONE"}},
        }

        last_response: dict[str, Any] = {}
        for attempt in range(2):
            response = post_json(
                "https://generativelanguage.googleapis.com/"
                f"v1beta/models/{model}:generateContent?key={key}",
                payload,
                timeout=self.timeout,
            )
            self._record_usage(response)
            last_response = response
            text = self._extract_text(response)
            if text:
                return text

            candidates = response.get("candidates")
            finish_reason = ""
            if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict):
                finish_reason = str(candidates[0].get("finishReason") or "")

            function_call = self._contains_function_call(response)
            if attempt == 0 and (
                function_call
                or finish_reason in {"MALFORMED_RESPONSE", "MAX_TOKENS", "OTHER"}
            ):
                if mode == "plan":
                    payload["generationConfig"] = dict(generation_config)
                    payload["generationConfig"]["responseJsonSchema"] = ACTION_SCHEMA
                if function_call:
                    payload["contents"] = [{
                        "role": "user",
                        "parts": [{
                            "text": (
                                "Do not call tools or functions. Return the requested final "
                                "text, source code, or JSON directly.\n\n" + prompt
                            )
                        }],
                    }]
                continue
            break

        raise ProviderError(
            "Unexpected Gemini response at maximum model output limit "
            f"({output_limit} tokens): {json.dumps(last_response)[:1200]}"
        )
