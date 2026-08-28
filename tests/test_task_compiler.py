from __future__ import annotations

from pathlib import Path

from sophyane.task_compiler import (
    decompose,
    estimate_difficulty,
    extract_explicit_facts,
    should_compile,
)


def test_easy_question_is_not_stolen_by_compiler():
    text = "What is 2 + 2?"

    assert estimate_difficulty(text) <= 2
    assert not should_compile(text)


def test_complex_engineering_task_is_compiler_candidate():
    text = (
        "Analyze slow orders queries, add a composite index on "
        "(user_id, status, created_at), and rewrite N+1 ORM queries."
    )

    assert estimate_difficulty(text) >= 3
    assert should_compile(text)


def test_explicit_user_facts_are_extracted():
    facts = extract_explicit_facts(
        "Open after 5 failures within 30 seconds and emit "
        "OrderPlaced with X-RateLimit-Limit."
    )

    assert "5" in facts
    assert any("30" in item for item in facts)
    assert "OrderPlaced" in facts
    assert "X-RateLimit-Limit" in facts


def test_decomposition_creates_bounded_requirements():
    parts = decompose(
        "Analyze the query, add an index, and rewrite the ORM fetch."
    )

    assert len(parts) >= 2
    assert all(item.requirement_id for item in parts)
    assert all(item.text for item in parts)


def test_production_module_does_not_embed_proof_task_solutions():
    source = Path(
        "src/sophyane/task_compiler.py"
    ).read_text()

    forbidden = (
        "idx_orders_user_id_status_created_at",
        "failure_threshold=5",
        "OrderPlaced through Kafka",
        "ZREMRANGEBYSCORE",
    )

    for value in forbidden:
        assert value not in source


def test_n_plus_one_does_not_create_fake_numeric_user_truth():
    facts = extract_explicit_facts(
        "Rewrite N+1 ORM queries using eager loading."
    )

    assert "1" not in facts


def test_real_standalone_numeric_facts_remain_authoritative():
    facts = extract_explicit_facts(
        "Open after 5 failures within 30 seconds."
    )

    assert "5" in facts
    assert any(item.startswith("30") for item in facts)


def test_lexical_repository_hit_is_not_automatic_truth():
    source = Path(
        "src/sophyane/task_compiler.py"
    ).read_text()

    # Repository evidence must not directly create valid=True evidence
    # and then continue past local residual resolution.
    forbidden = '''if hits:
            best = hits[0]

            evidence['''

    assert forbidden not in source
