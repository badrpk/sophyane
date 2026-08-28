from __future__ import annotations

from sophyane.task_compiler import (
    estimate_difficulty,
    should_compile,
)


def test_d1_arithmetic_is_easy():
    text = "What is 2 + 2?"

    assert estimate_difficulty(
        text
    ) <= 2

    assert not should_compile(
        text
    )


def test_d2_short_explanation_is_easy():
    text = (
        "Explain in one short sentence "
        "what HTTP 429 means."
    )

    assert estimate_difficulty(
        text
    ) <= 2


def test_bounded_retry_request_is_not_hard():
    text = (
        "Give one concise exponential-backoff "
        "retry policy with maximum 3 retries."
    )

    assert estimate_difficulty(
        text
    ) <= 3


def test_architecture_request_is_compiler_candidate():
    text = (
        "Integrate a circuit breaker around the primary payment "
        "gateway HTTP client and fall back to a secondary processor "
        "after repeated failures."
    )

    assert estimate_difficulty(
        text
    ) >= 3
