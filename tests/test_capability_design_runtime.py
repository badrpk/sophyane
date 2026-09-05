from __future__ import annotations


def test_detects_generic_capability_expansion():
    from sophyane.capability_design import (
        detect_capability_design_intent,
    )

    requests = (
        "Sophyane should be able to process documents",
        "I want Sophyane to understand uploaded files",
        "add support for structured data ingestion",
        "give Sophyane the ability to generate speech",
        "Sophyane should have all features as another platform",
    )

    for request in requests:
        result = detect_capability_design_intent(
            request
        )

        assert result.requested is True


def test_normal_information_question_is_not_forced_into_design():
    from sophyane.capability_design import (
        detect_capability_design_intent,
    )

    result = detect_capability_design_intent(
        "what is a state graph?"
    )

    assert result.requested is False


def test_design_prompt_requires_systematic_description():
    from sophyane.capability_design import (
        systematic_capability_prompt,
    )

    text = systematic_capability_prompt(
        request=(
            "Sophyane should support a new capability"
        ),
        conversational_context="",
    )

    assert "Capability goal" in text
    assert "User-facing abilities" in text
    assert "Functional capability groups" in text
    assert "Processing architecture" in text
    assert "Verification" in text
    assert "Incremental implementation path" in text
    assert "PROCESS_FLOW:" in text


def test_design_prompt_forbids_premature_graph():
    from sophyane.capability_design import (
        systematic_capability_prompt,
    )

    text = systematic_capability_prompt(
        request="Sophyane should support something new",
        conversational_context="",
    )

    assert (
        "Do not output a graph or Mermaid"
        in text
    )


def test_design_layer_is_not_domain_specific():
    from pathlib import Path

    source = Path(
        "src/sophyane/capability_design.py"
    ).read_text(
        encoding="utf-8",
    ).lower()

    forbidden = (
        "elevenlabs",
        "eleven labs",
        "nifdu",
        "gemini",
        "chatgpt-browser",
    )

    for value in forbidden:
        assert value not in source


def test_process_flow_is_compatible_with_existing_retention():
    from sophyane.conversational_graph import (
        extract_grounded_process_steps,
    )

    response = (
        "Capability architecture description.\n\n"
        "PROCESS_FLOW: "
        "input ingestion -> validation -> extraction -> "
        "understanding -> transformation -> output generation -> "
        "verification"
    )

    #
    # The existing graph extractor sees an ordered grounded sequence.
    #
    process = response.split(
        "PROCESS_FLOW:",
        1,
    )[1].strip()

    steps = extract_grounded_process_steps(
        process
    )

    labels = [
        step.label
        for step in steps
    ]

    assert labels == [
        "input ingestion",
        "validation",
        "extraction",
        "understanding",
        "transformation",
        "output generation",
        "verification",
    ]
