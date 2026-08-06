import pytest

from sophyane.semantic_intent_router import (
    SemanticDomain,
    classify_semantic_domain,
)


@pytest.mark.parametrize(
    "query",
    [
        "what is name of my usa company",
        "which US company do I own?",
        "what company in America did I register?",
        "what is my company in the United States?",
    ],
)
def test_personal_company_questions_are_private(
    query: str,
) -> None:
    decision = classify_semantic_domain(
        query
    )

    assert (
        decision.domain
        == SemanticDomain.PERSONAL_KNOWLEDGE
    )
    assert decision.personal is True
    assert (
        decision.public_fallback_allowed
        is False
    )


def test_public_company_question_remains_public() -> None:
    decision = classify_semantic_domain(
        "what is the largest company in the USA?"
    )

    assert (
        decision.domain
        == SemanticDomain.PUBLIC_KNOWLEDGE
    )
    assert decision.personal is False


def test_policy_instruction_is_not_an_email_search() -> None:
    decision = classify_semantic_domain(
        "when I ask personal information, "
        "search my email"
    )

    assert (
        decision.domain
        == SemanticDomain.POLICY_INSTRUCTION
    )


def test_website_build_remains_artifact_creation() -> None:
    decision = classify_semantic_domain(
        "make a website about USA companies"
    )

    assert (
        decision.domain
        == SemanticDomain.ARTIFACT_CREATION
    )


@pytest.mark.parametrize(
    "query",
    [
        "what company did I register in America?",
        "which company have I registered in the USA?",
        "what business did I form in the United States?",
        "which American company did I incorporate?",
    ],
)
def test_personal_company_question_grammar_variants(
    query: str,
) -> None:
    decision = classify_semantic_domain(query)

    assert (
        decision.domain
        == SemanticDomain.PERSONAL_KNOWLEDGE
    )
    assert decision.personal is True
    assert decision.public_fallback_allowed is False
