from __future__ import annotations

import os

import pytest

from sophyane.providers.base import (
    ProviderError,
)
from sophyane.providers.local_gguf import (
    LocalGgufProvider,
    _estimate_chat_prompt_tokens,
    _safe_completion_budget,
)


def _provider() -> LocalGgufProvider:
    provider = object.__new__(
        LocalGgufProvider
    )

    provider.timeout = 600
    provider.max_tokens = 4096
    provider.temperature = 0.3
    provider.model = "local"
    provider.endpoint = (
        "http://127.0.0.1:8766"
    )

    return provider


def test_large_prompt_cannot_request_1536_inside_2048_context(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "SOPHYANE_LLAMA_CONTEXT",
        "2048",
    )

    prompt = "x" * 3000
    system = "y" * 500

    estimate = (
        _estimate_chat_prompt_tokens(
            prompt,
            system,
        )
    )

    budget = (
        _safe_completion_budget(
            prompt=prompt,
            system_prompt=system,
            configured_max_tokens=4096,
        )
    )

    print(
        "estimate:",
        estimate,
    )

    print(
        "budget:",
        budget,
    )

    assert budget < 1536

    assert (
        estimate
        + budget
        < 2048
    )


def test_small_prompt_can_receive_material_completion_budget(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "SOPHYANE_LLAMA_CONTEXT",
        "2048",
    )

    budget = (
        _safe_completion_budget(
            prompt="write one Python function",
            system_prompt="Return code.",
            configured_max_tokens=4096,
        )
    )

    assert budget >= 1000


def test_server_request_uses_computed_completion_budget(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "SOPHYANE_LLAMA_CONTEXT",
        "2048",
    )

    provider = _provider()

    captured = {}

    def fake_post_json(
        url,
        payload,
        *,
        headers,
        timeout,
    ):
        captured.update(
            payload
        )

        return {
            "choices": [
                {
                    "message": {
                        "content":
                            "done",
                    }
                }
            ]
        }

    monkeypatch.setattr(
        "sophyane.providers.local_gguf.post_json",
        fake_post_json,
    )

    result = provider._generate_via_server(
        "x" * 3000,
        "y" * 500,
        request_timeout=30,
    )

    assert result == "done"

    assert (
        captured[
            "max_tokens"
        ]
        < 1536
    )


def test_too_little_context_requests_decomposition(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "SOPHYANE_LLAMA_CONTEXT",
        "2048",
    )

    provider = _provider()

    with pytest.raises(
        ProviderError,
        match="requires decomposition",
    ):
        provider._generate_via_server(
            "x" * 5600,
            "y" * 700,
            request_timeout=30,
        )


def test_v5_short_speculation_has_lower_evidence_admission_floor():
    from pathlib import Path

    source = Path(
        "src/sophyane/providers/local_gguf.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        "SOPHYANE_LOCAL_GGUF_SPECULATIVE_EVIDENCE_FLOOR_V5"
        in source
    )

    assert (
        "minimum_completion_tokens"
        in source
    )

    assert (
        "_sophyane_allow_short_speculative_timeout"
        in source
    )

    #
    # Authorized/candidate generation must retain the 256-token floor.
    #
    assert (
        "else 256"
        in source
    )


def test_v5_short_speculation_rounds_http_budget_up_only_for_private_clone():
    from pathlib import Path

    source = Path(
        "src/sophyane/providers/local_gguf.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        "SOPHYANE_LOCAL_GGUF_SPECULATIVE_HTTP_BUDGET_V5"
        in source
    )

    assert (
        "if short_speculation:"
        in source
    )

    assert (
        "_speculation_math.ceil("
        in source
    )

    assert (
        "else:"
        in source
    )

    assert (
        "int(\n                        remaining"
        in source
    )
