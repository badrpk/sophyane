from __future__ import annotations

from pathlib import Path


GROUNDING = (
    "PDF ingestion -> validation -> text extraction -> "
    "page structure -> chunking -> semantic processing -> "
    "TTS preparation -> speech generation -> verification"
)


def test_followup_language_includes_natural_flow_phrases():
    from sophyane.conversational_graph import (
        is_conversational_graph_followup,
    )

    positive = (
        "show graph",
        "show me the flow",
        "visualize this",
        "visualize the architecture",
        "show how this works visually",
        "make a process graph",
    )

    for request in positive:
        assert (
            is_conversational_graph_followup(
                request
            )
            is True
        )


def test_first_turn_request_is_not_graph_followup():
    from sophyane.conversational_graph import (
        is_conversational_graph_followup,
    )

    assert (
        is_conversational_graph_followup(
            (
                "I want Sophyane to import PDF "
                "and process it like ElevenLabs"
            )
        )
        is False
    )


def test_grounded_process_extraction_preserves_order():
    from sophyane.conversational_graph import (
        extract_grounded_process_steps,
    )

    steps = extract_grounded_process_steps(
        GROUNDING
    )

    labels = [
        item.label
        for item in steps
    ]

    assert labels == [
        "PDF ingestion",
        "validation",
        "text extraction",
        "page structure",
        "chunking",
        "semantic processing",
        "TTS preparation",
        "speech generation",
        "verification",
    ]


def test_process_graph_uses_existing_stategraph():
    from sophyane.conversational_graph import (
        build_process_graph,
        extract_grounded_process_steps,
    )

    from sophyane.graph_runtime import (
        StateGraph,
    )

    graph = build_process_graph(
        extract_grounded_process_steps(
            GROUNDING
        )
    )

    assert isinstance(
        graph,
        StateGraph,
    )

    assert (
        graph.edges[
            StateGraph.START
        ]
        == "pdf_ingestion"
    )

    assert (
        graph.edges[
            "speech_generation"
        ]
        == "verification"
    )

    assert (
        graph.edges[
            "verification"
        ]
        == StateGraph.END
    )


def test_mermaid_reuses_existing_graph_topology():
    from sophyane.conversational_graph import (
        render_process_mermaid,
    )

    result = render_process_mermaid(
        GROUNDING
    )

    assert result[
        "handled"
    ] is True

    text = result[
        "mermaid"
    ]

    assert "flowchart TD" in text

    assert (
        "pdf_ingestion[PDF ingestion]"
        in text
    )

    assert (
        "speech_generation["
        "speech generation]"
        in text
    )

    assert (
        "pdf_ingestion --> validation"
        in text
    )


def test_no_grounding_means_no_fabricated_process():
    from sophyane.conversational_graph import (
        render_process_mermaid,
    )

    result = render_process_mermaid(
        "Sophyane should support PDFs."
    )

    assert result[
        "handled"
    ] is False


def test_graph_artifacts_are_grounded_and_materialized(
    tmp_path: Path,
):
    from sophyane.conversational_graph import (
        save_process_graph_artifacts,
    )

    result = save_process_graph_artifacts(
        description=GROUNDING,
        workspace=tmp_path,
    )

    assert result[
        "handled"
    ] is True

    mermaid = Path(
        result[
            "mermaid_path"
        ]
    )

    payload = Path(
        result[
            "json_path"
        ]
    )

    assert mermaid.is_file()
    assert payload.is_file()

    assert (
        "conversation-grounded"
        in payload.read_text(
            encoding="utf-8"
        )
    )


def test_numeric_visualization_remains_separate():
    from sophyane.visualization_capability import (
        extract_grounded_points,
    )

    points = extract_grounded_points(
        "Jan: 10, Feb: 20"
    )

    assert len(
        points
    ) == 2
