from __future__ import annotations

from pathlib import Path

import pytest

import sophyane.providers.local_gguf as local_gguf_module
from sophyane.providers.base import ProviderError
from sophyane.providers.local_gguf import (
    LocalGgufProvider,
)


def _provider() -> LocalGgufProvider:
    provider = object.__new__(
        LocalGgufProvider
    )

    provider.timeout = 600
    provider.max_tokens = 4096
    provider.cli_path = None
    provider.gguf_path = None

    return provider


def test_generate_contains_exactly_one_server_generation_call() -> None:
    source = Path(
        "src/sophyane/providers/local_gguf.py"
    ).read_text(
        encoding="utf-8",
    )

    marker = (
        "SOPHYANE_LOCAL_GGUF_SINGLE_REAL_GENERATION_V1"
    )

    assert marker in source

    region = source[
        source.index(
            marker
        ):
        source.index(
            "    def _generate_via_server(",
            source.index(
                marker
            ),
        )
    ]

    assert (
        region.count(
            "self._generate_via_server("
        )
        == 1
    )


def test_real_generation_timeout_is_not_retried(
    monkeypatch,
) -> None:
    provider = _provider()

    monkeypatch.setattr(
        "sophyane.local_server.wait_until_ready",
        lambda timeout:
            True,
    )

    calls = []

    def fail_generation(
        prompt,
        system_prompt,
        *,
        request_timeout=None,
    ):
        calls.append(
            request_timeout
        )

        raise ProviderError(
            "ORIGINAL_REAL_GENERATION_TIMEOUT"
        )

    provider._generate_via_server = (
        fail_generation
    )

    with pytest.raises(
        ProviderError,
        match="ORIGINAL_REAL_GENERATION_TIMEOUT",
    ):
        provider.generate(
            "write code",
            "system",
        )

    assert len(
        calls
    ) == 1


def test_readiness_recovery_can_start_server_before_generation(
    monkeypatch,
) -> None:
    provider = _provider()

    readiness = iter(
        (
            False,
            True,
        )
    )

    monkeypatch.setattr(
        "sophyane.local_server.wait_until_ready",
        lambda timeout:
            next(
                readiness
            ),
    )

    monkeypatch.setattr(
        "sophyane.local_server.ensure_server_background",
        lambda:
            (
                True,
                "llama-server is loading on 8766",
            ),
    )

    monkeypatch.setattr(
        "sophyane.local_server.failure_detail",
        lambda:
            "",
    )

    calls = []

    def generation(
        prompt,
        system_prompt,
        *,
        request_timeout=None,
    ):
        calls.append(
            request_timeout
        )
        return "done"

    provider._generate_via_server = (
        generation
    )

    result = provider.generate(
        "write code",
        "system",
    )

    assert result == "done"

    assert len(
        calls
    ) == 1
