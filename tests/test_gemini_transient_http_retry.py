from __future__ import annotations

import pytest

from sophyane.providers import gemini as gemini_module
from sophyane.providers.base import ProviderError
from sophyane.providers.gemini import GeminiProvider


def _provider() -> GeminiProvider:
    provider = GeminiProvider(
        api_key="test-key",
        model="gemini-test",
    )
    provider._model_output_limit = 65536
    return provider


def _success() -> dict:
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": "retry succeeded",
                        }
                    ]
                }
            }
        ],
        "usageMetadata": {},
    }


def test_gemini_retries_503_then_succeeds(
    monkeypatch,
) -> None:
    provider = _provider()
    calls = 0

    monkeypatch.setenv(
        "SOPHYANE_GEMINI_MAX_ATTEMPTS",
        "3",
    )
    monkeypatch.setenv(
        "SOPHYANE_GEMINI_RETRY_BASE_SECONDS",
        "0",
    )
    monkeypatch.setattr(
        gemini_module,
        "cancelled",
        lambda: False,
    )

    def fake_post_json(
        _url,
        _payload,
        timeout,
    ):
        nonlocal calls
        calls += 1
        assert timeout == provider.timeout

        if calls < 3:
            raise ProviderError(
                'HTTP 503: {"error":{"status":"UNAVAILABLE"}}'
            )

        return _success()

    monkeypatch.setattr(
        gemini_module,
        "post_json",
        fake_post_json,
    )

    assert (
        provider.generate(
            "hello",
            "SOPHYANE_RESPONSE_MODE: CHAT",
        )
        == "retry succeeded"
    )
    assert calls == 3


@pytest.mark.parametrize(
    "status",
    [
        429,
        500,
        502,
        503,
        504,
    ],
)
def test_all_transient_statuses_are_retryable(
    monkeypatch,
    status: int,
) -> None:
    provider = _provider()
    calls = 0

    monkeypatch.setenv(
        "SOPHYANE_GEMINI_MAX_ATTEMPTS",
        "2",
    )
    monkeypatch.setenv(
        "SOPHYANE_GEMINI_RETRY_BASE_SECONDS",
        "0",
    )
    monkeypatch.setattr(
        gemini_module,
        "cancelled",
        lambda: False,
    )

    def fake_post_json(
        _url,
        _payload,
        timeout,
    ):
        nonlocal calls
        calls += 1

        if calls == 1:
            raise ProviderError(
                f"HTTP {status}: transient"
            )

        return _success()

    monkeypatch.setattr(
        gemini_module,
        "post_json",
        fake_post_json,
    )

    assert (
        provider.generate(
            "hello",
            "SOPHYANE_RESPONSE_MODE: CHAT",
        )
        == "retry succeeded"
    )
    assert calls == 2


@pytest.mark.parametrize(
    "status",
    [
        400,
        401,
        403,
        404,
    ],
)
def test_terminal_http_statuses_fail_without_retry(
    monkeypatch,
    status: int,
) -> None:
    provider = _provider()
    calls = 0

    monkeypatch.setenv(
        "SOPHYANE_GEMINI_MAX_ATTEMPTS",
        "3",
    )
    monkeypatch.setenv(
        "SOPHYANE_GEMINI_RETRY_BASE_SECONDS",
        "0",
    )
    monkeypatch.setattr(
        gemini_module,
        "cancelled",
        lambda: False,
    )

    def fake_post_json(
        _url,
        _payload,
        timeout,
    ):
        nonlocal calls
        calls += 1
        raise ProviderError(
            f"HTTP {status}: terminal"
        )

    monkeypatch.setattr(
        gemini_module,
        "post_json",
        fake_post_json,
    )

    with pytest.raises(
        ProviderError,
        match=rf"HTTP {status}",
    ):
        provider.generate(
            "hello",
            "SOPHYANE_RESPONSE_MODE: CHAT",
        )

    assert calls == 1


def test_transient_retry_is_bounded(
    monkeypatch,
) -> None:
    provider = _provider()
    calls = 0

    monkeypatch.setenv(
        "SOPHYANE_GEMINI_MAX_ATTEMPTS",
        "3",
    )
    monkeypatch.setenv(
        "SOPHYANE_GEMINI_RETRY_BASE_SECONDS",
        "0",
    )
    monkeypatch.setattr(
        gemini_module,
        "cancelled",
        lambda: False,
    )

    def fake_post_json(
        _url,
        _payload,
        timeout,
    ):
        nonlocal calls
        calls += 1
        raise ProviderError(
            "HTTP 503: still unavailable"
        )

    monkeypatch.setattr(
        gemini_module,
        "post_json",
        fake_post_json,
    )

    with pytest.raises(
        ProviderError,
        match="HTTP 503",
    ):
        provider.generate(
            "hello",
            "SOPHYANE_RESPONSE_MODE: CHAT",
        )

    assert calls == 3


def test_non_http_provider_error_is_not_retried(
    monkeypatch,
) -> None:
    provider = _provider()
    calls = 0

    monkeypatch.setenv(
        "SOPHYANE_GEMINI_MAX_ATTEMPTS",
        "3",
    )
    monkeypatch.setenv(
        "SOPHYANE_GEMINI_RETRY_BASE_SECONDS",
        "0",
    )
    monkeypatch.setattr(
        gemini_module,
        "cancelled",
        lambda: False,
    )

    def fake_post_json(
        _url,
        _payload,
        timeout,
    ):
        nonlocal calls
        calls += 1
        raise ProviderError(
            "Connection failed: offline"
        )

    monkeypatch.setattr(
        gemini_module,
        "post_json",
        fake_post_json,
    )

    with pytest.raises(
        ProviderError,
        match="Connection failed",
    ):
        provider.generate(
            "hello",
            "SOPHYANE_RESPONSE_MODE: CHAT",
        )

    assert calls == 1


def test_cancellation_prevents_http_attempt(
    monkeypatch,
) -> None:
    provider = _provider()
    calls = 0

    monkeypatch.setattr(
        gemini_module,
        "cancelled",
        lambda: True,
    )

    def fake_post_json(
        _url,
        _payload,
        timeout,
    ):
        nonlocal calls
        calls += 1
        return _success()

    monkeypatch.setattr(
        gemini_module,
        "post_json",
        fake_post_json,
    )

    with pytest.raises(
        ProviderError,
        match="provider generation cancelled",
    ):
        provider.generate(
            "hello",
            "SOPHYANE_RESPONSE_MODE: CHAT",
        )

    assert calls == 0


def test_retry_configuration_is_hard_bounded(
    monkeypatch,
) -> None:
    provider = _provider()

    monkeypatch.setenv(
        "SOPHYANE_GEMINI_MAX_ATTEMPTS",
        "999",
    )
    monkeypatch.setenv(
        "SOPHYANE_GEMINI_RETRY_BASE_SECONDS",
        "999",
    )

    assert provider._retry_settings() == (
        6,
        10.0,
    )
