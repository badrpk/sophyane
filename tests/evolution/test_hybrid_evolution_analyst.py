import inspect

from sophyane.evolution.engine import (
    EvolutionEngine,
)


def test_evolution_analyst_has_local_fallback() -> None:
    source = inspect.getsource(
        EvolutionEngine._analyst_llm
    )

    assert "_gemini" in source
    assert "_evolution_local_llm" in source
    assert (
        "SOPHYANE_EVOLUTION_ALLOW_LOCAL_FALLBACK"
        in source
    )
    assert (
        "SOPHYANE_EVOLUTION_FORCE_LOCAL_ANALYST"
        in source
    )


def test_local_analyst_uses_separate_endpoint() -> None:
    source = inspect.getsource(
        EvolutionEngine._evolution_local_llm
    )

    assert "8767" in source
    assert "local-evolution" in source
    assert "/v1/chat/completions" in source


def test_quota_failure_allows_local_fallback() -> None:
    error = RuntimeError(
        "Gemini daily quota is exhausted: "
        "free_tier_requests"
    )

    assert (
        EvolutionEngine
        ._cloud_failure_allows_local_fallback(
            error
        )
        is True
    )


def test_503_allows_local_fallback() -> None:
    error = RuntimeError(
        "Gemini HTTP request failed. status=503"
    )

    assert (
        EvolutionEngine
        ._cloud_failure_allows_local_fallback(
            error
        )
        is True
    )


def test_programming_error_does_not_fallback() -> None:
    error = ValueError(
        "Candidate path policy is invalid"
    )

    assert (
        EvolutionEngine
        ._cloud_failure_allows_local_fallback(
            error
        )
        is False
    )
