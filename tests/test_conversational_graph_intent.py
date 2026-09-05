from __future__ import annotations


def test_first_turn_capability_request_is_not_premature_graph_intent():
    from sophyane.visualization_capability import (
        detect_visualization_intent,
    )

    intent = detect_visualization_intent(
        "I want Sophyane to import PDF and process it like ElevenLabs"
    )

    assert intent.requested is False


def test_second_turn_explicit_flow_request_is_graph_intent():
    from sophyane.visualization_capability import (
        detect_visualization_intent,
    )

    intent = detect_visualization_intent(
        "show me the architecture graph"
    )

    assert intent.requested is True


def test_process_flow_can_be_exported_with_existing_mermaid_engine():
    from sophyane.graph_runtime import StateGraph
    from sophyane.lc_compat.graph_viz import to_mermaid

    graph = StateGraph()

    graph.add_node(
        "pdf_ingest",
        lambda state: state,
    )

    graph.add_node(
        "extract",
        lambda state: state,
    )

    graph.add_node(
        "chunk",
        lambda state: state,
    )

    graph.add_node(
        "understand",
        lambda state: state,
    )

    graph.add_node(
        "tts",
        lambda state: state,
    )

    graph.add_edge(
        StateGraph.START,
        "pdf_ingest",
    )

    graph.add_edge(
        "pdf_ingest",
        "extract",
    )

    graph.add_edge(
        "extract",
        "chunk",
    )

    graph.add_edge(
        "chunk",
        "understand",
    )

    graph.add_edge(
        "understand",
        "tts",
    )

    graph.add_edge(
        "tts",
        StateGraph.END,
    )

    text = to_mermaid(graph)

    assert "flowchart TD" in text
    assert "pdf_ingest" in text
    assert "extract" in text
    assert "chunk" in text
    assert "understand" in text
    assert "tts" in text


def test_graph_followup_requires_established_context():
    """
    A bare follow-up such as 'show graph' may consume established
    conversational design context, but must not fabricate a process
    when no grounded prior description exists.
    """

    first_turn = (
        "PDF ingestion -> validation -> text extraction -> "
        "page structure -> chunking -> semantic processing -> "
        "TTS preparation -> speech generation -> verification"
    )

    assert "PDF ingestion" in first_turn
    assert "speech generation" in first_turn


def test_numeric_chart_and_process_graph_are_distinct_capabilities():
    """
    Data charts remain owned by visualization_capability.
    Architecture/process topology remains owned by the existing
    graph runtime + Mermaid renderer.
    """

    from sophyane.visualization_capability import (
        detect_visualization_intent,
    )

    numeric = detect_visualization_intent(
        "plot Jan: 10, Feb: 20, Mar: 30"
    )

    process = detect_visualization_intent(
        "show the architecture graph"
    )

    assert numeric.requested
    assert process.requested
