"""Regression tests for Sophyane's autonomous execution contract."""

from sophyane.agent import SYSTEM_PROMPT


def test_requires_evidence_for_completion_claims() -> None:
    prompt = SYSTEM_PROMPT.lower()
    assert "evidence is mandatory" in prompt
    assert "never claim" in prompt
    assert "exit code" in prompt


def test_requires_acceptance_criteria_and_repair_loop() -> None:
    prompt = SYSTEM_PROMPT.lower()
    assert "acceptance criteria" in prompt
    assert "bounded repair loop" in prompt
    assert "smallest safe fix" in prompt


def test_prevents_backend_to_html_misrouting() -> None:
    prompt = SYSTEM_PROMPT.lower()
    assert "rest api" in prompt
    assert "index.html" in prompt
    assert "artifact types correctly" in prompt


def test_avoids_unnecessary_questionnaires_and_disclaimers() -> None:
    prompt = SYSTEM_PROMPT.lower()
    assert "reasonable, clearly stated assumptions" in prompt
    assert "do not replace a solvable task with a questionnaire" in prompt
    assert "do not repeatedly recite generic ai limitations" in prompt
