from __future__ import annotations

from sophyane import (
    sli_capability_engine as engine,
)


HARNESS = (
    "Configure an AI agent to execute local test suites "
    "such as PyTest or Jest, capture stack traces upon "
    "test failure, parse the relevant source files, "
    "write a code patch, and re-run verification checks "
    "iteratively until the build turns green."
)


def test_harness_request_is_not_web():
    assert (
        engine.is_web_request(
            HARNESS
        )
        is False
    )


def test_ui_does_not_match_suites():
    assert (
        engine.is_web_request(
            "execute local test suites"
        )
        is False
    )


def test_ui_as_word_is_web():
    assert (
        engine.is_web_request(
            "create a UI"
        )
        is True
    )


def test_website_request_is_web():
    assert (
        engine.is_web_request(
            "build a website"
        )
        is True
    )


def test_non_web_scorer_is_neutral():
    score, issues = (
        engine._score_web_candidate(
            HARNESS,
            [],
        )
    )

    assert score == 0.0
    assert issues == []


def test_web_scorer_requires_index():
    score, issues = (
        engine._score_web_candidate(
            "build a website",
            [],
        )
    )

    assert score == -100.0
    assert "missing index.html" in issues
