import inspect

from sophyane.evolution.engine import (
    EvolutionEngine,
)


def test_gemini_checks_finish_reason() -> None:
    source = inspect.getsource(
        EvolutionEngine._gemini
    )

    assert "finishReason" in source
    assert "MAX_TOKENS" in source
    assert "usageMetadata" in source


def test_gemini_has_configurable_output_and_thinking() -> None:
    source = inspect.getsource(
        EvolutionEngine._gemini
    )

    assert (
        "SOPHYANE_EVOLUTION_GEMINI_MAX_OUTPUT_TOKENS"
        in source
    )
    assert (
        "SOPHYANE_EVOLUTION_GEMINI_THINKING_BUDGET"
        in source
    )
    assert '"thinkingBudget"' in source
