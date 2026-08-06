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


def test_candidate_cli_has_no_cloud_only_preflight() -> None:
    from pathlib import Path

    source = Path(
        "tools/sophyane_candidate_evolution.py"
    ).read_text(encoding="utf-8")

    assert (
        "Candidate generation requires the cloud analyst"
        not in source
    )
    assert "if not evolver.cloud_available()" not in source


def test_candidate_generation_has_no_gemini_only_gate() -> None:
    import inspect

    from sophyane.evolution.candidate_evolution import (
        CandidateEvolver,
    )

    source = inspect.getsource(
        CandidateEvolver.generate_proposal
    )

    assert "A Gemini key is required" not in source
    assert "_analyst_llm" in source


def test_candidate_repair_has_no_gemini_only_gate() -> None:
    import inspect

    from sophyane.evolution.candidate_evolution import (
        CandidateEvolver,
    )

    source = inspect.getsource(
        CandidateEvolver._repair_unapplicable_patch
    )

    assert (
        "Gemini is unavailable for one repair attempt"
        not in source
    )
    assert "_analyst_llm" in source


def test_local_analyst_bounds_prompt_and_output() -> None:
    import inspect

    from sophyane.evolution.engine import (
        EvolutionEngine,
    )

    source = inspect.getsource(
        EvolutionEngine._evolution_local_llm
    )

    assert (
        "SOPHYANE_EVOLUTION_LOCAL_MAX_PROMPT_CHARS"
        in source
    )
    assert (
        "SOPHYANE_EVOLUTION_LOCAL_MAX_OUTPUT_TOKENS"
        in source
    )
    assert "effective_max_tokens" in source
    assert "PROMPT COMPACTED" in source


def test_local_http_error_includes_response_body() -> None:
    import inspect

    from sophyane.evolution.engine import (
        EvolutionEngine,
    )

    source = inspect.getsource(
        EvolutionEngine._evolution_local_llm
    )

    assert "urllib.error.HTTPError" in source
    assert "error.read()" in source
    assert "prompt_characters" in source


def test_local_analyst_accepts_true_micro_budgets() -> None:
    import inspect

    from sophyane.evolution.engine import (
        EvolutionEngine,
    )

    source = inspect.getsource(
        EvolutionEngine._evolution_local_llm
    )

    assert "prompt_character_limit = max(\n            512," in source
    assert "local_output_limit = max(\n            32," in source
    assert "max(16, int(max_tokens))" in source
