from __future__ import annotations

import pytest

from sophyane.providers.base import Provider, ProviderMetadata
from sophyane.providers.fallback import FallbackProvider


class RecordingProvider(Provider):
    metadata = ProviderMetadata(
        provider_id="fake",
        display_name="Fake",
        default_model="fake",
        environment_variable="",
        requires_api_key=False,
    )

    def __init__(
        self,
        *,
        name: str,
        timeout: int = 300,
        error: Exception | None = None,
        result: str = "",
    ) -> None:
        super().__init__(
            api_key="",
            model=name,
            timeout=timeout,
            temperature=0.0,
            max_tokens=100,
        )
        self.error = error
        self.result = result
        self.observed_timeouts: list[int] = []

    def generate(self, prompt: str, system_prompt: str) -> str:
        self.observed_timeouts.append(self.timeout)

        if self.error is not None:
            raise self.error

        return self.result


def test_hard_cloud_failure_caps_local_coding_rescue() -> None:
    cloud = RecordingProvider(
        name="gemini",
        error=RuntimeError(
            "HTTP 429: insufficient_quota: exceeded your current quota"
        ),
    )

    local = RecordingProvider(
        name="local",
        timeout=300,
        result="LOCAL_OK",
    )

    provider = FallbackProvider(
        [
            ("gemini", cloud),
            ("local_gguf", local),
        ],
        primary="gemini",
    )

    assert (
        provider.generate(
            "prompt",
            "system",
            local_rescue_timeout=60,
        )
        == "LOCAL_OK"
    )

    assert local.observed_timeouts == [60]

    # Per-call mutation must be transactional.
    assert local.timeout == 300


def test_transient_cloud_failure_does_not_cap_local_fallback() -> None:
    cloud = RecordingProvider(
        name="gemini",
        error=RuntimeError("temporary network timeout"),
    )

    local = RecordingProvider(
        name="local",
        timeout=300,
        result="LOCAL_OK",
    )

    provider = FallbackProvider(
        [
            ("gemini", cloud),
            ("local_gguf", local),
        ],
        primary="gemini",
    )

    assert (
        provider.generate(
            "prompt",
            "system",
            local_rescue_timeout=60,
        )
        == "LOCAL_OK"
    )

    assert local.observed_timeouts == [300]
    assert local.timeout == 300


def test_local_primary_never_receives_rescue_cap() -> None:
    local = RecordingProvider(
        name="local",
        timeout=300,
        result="LOCAL_OK",
    )

    provider = FallbackProvider(
        [("local_gguf", local)],
        primary="local_gguf",
    )

    assert (
        provider.generate(
            "prompt",
            "system",
            local_rescue_timeout=60,
        )
        == "LOCAL_OK"
    )

    assert local.observed_timeouts == [300]
    assert local.timeout == 300


def test_no_rescue_budget_preserves_existing_timeout() -> None:
    cloud = RecordingProvider(
        name="gemini",
        error=RuntimeError(
            "HTTP 429: insufficient_quota"
        ),
    )

    local = RecordingProvider(
        name="local",
        timeout=300,
        result="LOCAL_OK",
    )

    provider = FallbackProvider(
        [
            ("gemini", cloud),
            ("local_gguf", local),
        ],
        primary="gemini",
    )

    assert provider.generate("prompt", "system") == "LOCAL_OK"
    assert local.observed_timeouts == [300]


def test_local_timeout_restored_when_rescue_fails() -> None:
    cloud = RecordingProvider(
        name="gemini",
        error=RuntimeError(
            "HTTP 429: insufficient_quota"
        ),
    )

    local = RecordingProvider(
        name="local",
        timeout=300,
        error=RuntimeError("local inference timeout"),
    )

    provider = FallbackProvider(
        [
            ("gemini", cloud),
            ("local_gguf", local),
        ],
        primary="gemini",
    )

    with pytest.raises(Exception):
        provider.generate(
            "prompt",
            "system",
            local_rescue_timeout=60,
        )

    assert local.observed_timeouts == [60]
    assert local.timeout == 300


def test_shared_rescue_budget_exhaustion_skips_later_local_attempt(
    monkeypatch,
) -> None:
    import sophyane.providers.fallback as fallback_module
    from sophyane.providers.fallback import LocalRescueBudget

    clock_values = iter(
        [
            # First cloud call start/end.
            0.0,
            0.1,
            # First local call bookkeeping. This deliberately consumes
            # exactly five seconds of the shared local-rescue allowance.
            1.0,
            1.0,
            6.0,
            # Second cloud call start/end.
            7.0,
            7.1,
        ]
    )

    last_clock = [7.1]

    def fake_perf_counter() -> float:
        try:
            last_clock[0] = next(clock_values)
        except StopIteration:
            pass
        return last_clock[0]

    monkeypatch.setattr(
        fallback_module.time,
        "perf_counter",
        fake_perf_counter,
    )

    monkeypatch.setattr(
        fallback_module,
        "load_llm_config",
        lambda: {
            "allow_cloud_local_rescue": True,
        },
    )

    cloud = RecordingProvider(
        name="gemini",
        error=RuntimeError(
            "HTTP 429: insufficient_quota"
        ),
    )

    local = RecordingProvider(
        name="local",
        timeout=300,
        result="LOCAL_OK",
    )

    provider = FallbackProvider(
        [
            ("gemini", cloud),
            ("local_gguf", local),
        ],
        primary="gemini",
    )

    budget = LocalRescueBudget(
        remaining_seconds=5.0,
        per_attempt_seconds=60.0,
    )

    assert (
        provider.generate(
            "first",
            "system",
            local_rescue_timeout=60,
            local_rescue_budget=budget,
        )
        == "LOCAL_OK"
    )

    assert local.observed_timeouts == [5]
    assert budget.remaining_seconds == 0.0
    assert local.timeout == 300

    with pytest.raises(
        Exception,
        match="budget exhausted|providers failed|rate limit",
    ):
        provider.generate(
            "second",
            "system",
            local_rescue_timeout=60,
            local_rescue_budget=budget,
        )

    # No second local invocation after cumulative exhaustion.
    assert local.observed_timeouts == [5]
    assert local.timeout == 300


def test_shared_rescue_budget_is_not_consumed_by_cloud_latency(
    monkeypatch,
) -> None:
    import sophyane.providers.fallback as fallback_module
    from sophyane.providers.fallback import LocalRescueBudget

    # Cloud consumes ten seconds. Local consumes four seconds.
    clock = iter(
        [
            0.0,   # cloud started
            10.0,  # cloud failed
            10.0,  # local provider started
            10.0,  # local rescue budget timer
            14.0,  # local rescue budget consume
        ]
    )

    monkeypatch.setattr(
        fallback_module.time,
        "perf_counter",
        lambda: next(clock),
    )

    cloud = RecordingProvider(
        name="gemini",
        error=RuntimeError(
            "HTTP 429: insufficient_quota"
        ),
    )

    local = RecordingProvider(
        name="local",
        timeout=300,
        result="LOCAL_OK",
    )

    provider = FallbackProvider(
        [
            ("gemini", cloud),
            ("local_gguf", local),
        ],
        primary="gemini",
    )

    budget = LocalRescueBudget(
        remaining_seconds=20.0,
        per_attempt_seconds=60.0,
    )

    assert (
        provider.generate(
            "prompt",
            "system",
            local_rescue_timeout=60,
            local_rescue_budget=budget,
        )
        == "LOCAL_OK"
    )

    assert local.observed_timeouts == [20]

    # Only local time is charged. The ten seconds spent proving the cloud
    # quota failure do not consume the local rescue allowance.
    assert budget.remaining_seconds == 16.0
    assert local.timeout == 300


def test_shared_budget_does_not_change_local_primary_timeout() -> None:
    from sophyane.providers.fallback import LocalRescueBudget

    local = RecordingProvider(
        name="local",
        timeout=300,
        result="LOCAL_OK",
    )

    provider = FallbackProvider(
        [
            ("local_gguf", local),
        ],
        primary="local_gguf",
    )

    budget = LocalRescueBudget(
        remaining_seconds=1.0,
        per_attempt_seconds=1.0,
    )

    assert (
        provider.generate(
            "prompt",
            "system",
            local_rescue_timeout=60,
            local_rescue_budget=budget,
        )
        == "LOCAL_OK"
    )

    assert local.observed_timeouts == [300]
    assert budget.remaining_seconds == 1.0
    assert local.timeout == 300
