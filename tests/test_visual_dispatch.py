from pathlib import Path


def test_numeric_chart_routes_to_existing_visualization():
    from sophyane.visual_dispatch import (
        classify_visual_route,
    )

    result = classify_visual_route(
        "show a graph of Jan: 10 Feb: 20 Mar: 30"
    )

    assert result.requested is True
    assert result.route == "data_chart"


def test_capability_graph_routes_to_structural_graph():
    from sophyane.visual_dispatch import (
        classify_visual_route,
    )

    result = classify_visual_route(
        "show the capability graph A -> B -> C"
    )

    assert result.requested is True
    assert result.route == "structural_graph"


def test_graph_database_question_is_not_visual_execution():
    from sophyane.visual_dispatch import (
        classify_visual_route,
    )

    result = classify_visual_route(
        "what is a graph database?"
    )

    assert result.requested is False


def test_structural_graph_never_invents_edges(
    tmp_path: Path,
):
    from sophyane.visual_dispatch import (
        render_structural_graph,
    )

    result = render_structural_graph(
        request=(
            "show the capability graph"
        ),
        workspace=tmp_path,
    )

    assert result["handled"] is False
    assert not list(
        tmp_path.rglob(
            "*.mmd"
        )
    )


def test_structural_graph_writes_grounded_mermaid(
    tmp_path: Path,
):
    from sophyane.visual_dispatch import (
        render_structural_graph,
    )

    result = render_structural_graph(
        request=(
            "show workflow graph "
            "ingest -> validate, "
            "validate -> render"
        ),
        workspace=tmp_path,
    )

    assert result["handled"] is True
    assert result["edge_count"] == 2

    mermaid = Path(
        result["mermaid_path"]
    )

    data = Path(
        result["json_path"]
    )

    assert mermaid.is_file()
    assert data.is_file()

    text = mermaid.read_text(
        encoding="utf-8",
    )

    assert "flowchart TD" in text
    assert "ingest" in text
    assert "validate" in text
    assert "render" in text


def test_general_dispatch_renders_numeric_chart(
    tmp_path: Path,
):
    from sophyane.visual_dispatch import (
        try_general_visual_dispatch,
    )

    result = try_general_visual_dispatch(
        (
            "show monthly sales graph "
            "Jan: 10, Feb: 22, Mar: 18"
        ),
        workspace=tmp_path,
    )

    assert result is not None
    assert result["handled"] is True
    assert result["route"] == "data_chart"

    png = Path(
        result[
            "result"
        ][
            "png_path"
        ]
    )

    assert png.is_file()
    assert png.stat().st_size > 0


def test_general_dispatch_renders_structural_graph(
    tmp_path: Path,
):
    from sophyane.visual_dispatch import (
        try_general_visual_dispatch,
    )

    result = try_general_visual_dispatch(
        (
            "show execution graph "
            "prepare -> execute, "
            "execute -> verify"
        ),
        workspace=tmp_path,
    )

    assert result is not None
    assert result["handled"] is True
    assert result["route"] == "structural_graph"


def test_general_dispatch_falls_through_when_not_grounded(
    tmp_path: Path,
):
    from sophyane.visual_dispatch import (
        try_general_visual_dispatch,
    )

    result = try_general_visual_dispatch(
        "make a graph showing Alice is better than Bob",
        workspace=tmp_path,
    )

    assert result is None


def test_visual_followup_uses_session_imported_document(
    tmp_path,
):
    from sophyane.document_dispatch import (
        try_general_document_dispatch,
    )

    from sophyane.document_session_context import (
        clear_current_document,
    )

    from sophyane.visual_dispatch import (
        try_general_visual_dispatch,
    )

    path = (
        tmp_path
        / "sales.csv"
    )

    path.write_text(
        (
            "month,sales\n"
            "Jan,120\n"
            "Feb,160\n"
            "Mar,145\n"
            "Apr,210\n"
        ),
        encoding="utf-8",
    )

    clear_current_document()

    imported = (
        try_general_document_dispatch(
            "import sales.csv",
            workspace=tmp_path,
        )
    )

    assert imported is not None

    result = (
        try_general_visual_dispatch(
            "now graph the values in it",
            workspace=tmp_path,
        )
    )

    assert result is not None
    assert result["handled"] is True
    assert result["route"] == "data_chart"

    payload = result[
        "result"
    ]

    assert int(
        payload[
            "point_count"
        ]
    ) >= 2
