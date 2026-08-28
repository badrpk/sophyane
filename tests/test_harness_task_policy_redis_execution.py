from __future__ import annotations

from sophyane.harness_task_policy import (
    is_execution_request,
)


def test_original_redis_middleware_request_is_execution() -> None:
    request = (
        "Implement a sliding-window rate-limiting middleware using Redis "
        "and Lua scripts to restrict unauthenticated users to 100 req/min "
        "per IP. Return 429 Too Many Requests with Retry-After and "
        "X-RateLimit-* headers upon violation."
    )

    assert is_execution_request(request) is True


def test_concise_execute_redis_continuation_is_execution() -> None:
    request = (
        "Execute the Redis sliding-window rate-limit task now."
    )

    assert is_execution_request(request) is True


def test_redis_middleware_execute_is_execution() -> None:
    assert (
        is_execution_request(
            "Execute the Redis middleware implementation now."
        )
        is True
    )


def test_rate_limiting_execute_is_execution() -> None:
    assert (
        is_execution_request(
            "Execute the rate-limiting implementation now."
        )
        is True
    )


def test_lua_implementation_is_execution() -> None:
    assert (
        is_execution_request(
            "Implement the Lua sliding-window logic."
        )
        is True
    )


def test_redis_question_without_execution_verb_stays_direct() -> None:
    assert (
        is_execution_request(
            "What is Redis?"
        )
        is False
    )


def test_middleware_explanation_without_execution_verb_stays_direct() -> None:
    assert (
        is_execution_request(
            "Explain middleware."
        )
        is False
    )
