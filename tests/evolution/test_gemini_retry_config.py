import inspect

from sophyane.evolution.engine import (
    EvolutionEngine,
)


def test_gemini_retries_transient_http_errors() -> None:
    source = inspect.getsource(
        EvolutionEngine._gemini
    )

    assert "retryable_statuses" in source
    assert "503" in source
    assert "429" in source
    assert "Retry-After" in source
    assert "random.uniform" in source
    assert "time.sleep" in source


def test_gemini_retry_policy_is_bounded_and_configurable() -> None:
    source = inspect.getsource(
        EvolutionEngine._gemini
    )

    assert (
        "SOPHYANE_EVOLUTION_GEMINI_MAX_ATTEMPTS"
        in source
    )
    assert (
        "SOPHYANE_EVOLUTION_GEMINI_RETRY_BASE_SECONDS"
        in source
    )
    assert "max_attempts + 1" in source
