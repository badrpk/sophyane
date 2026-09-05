from __future__ import annotations


def test_explicit_graph_intent_is_detected():
    from sophyane.visualization_capability import (
        detect_visualization_intent,
    )

    intent = detect_visualization_intent(
        "make a graph of monthly sales"
    )

    assert intent.requested is True
    assert intent.explicit is True
    assert intent.chart_type == "line"


def test_implicit_trend_intent_is_detected():
    from sophyane.visualization_capability import (
        detect_visualization_intent,
    )

    intent = detect_visualization_intent(
        "show how sales changed each month"
    )

    assert intent.requested is True
    assert intent.explicit is False
    assert intent.chart_type == "line"


def test_compare_visually_selects_bar_chart():
    from sophyane.visualization_capability import (
        detect_visualization_intent,
    )

    intent = detect_visualization_intent(
        "compare PRL NRL and ATRL visually"
    )

    assert intent.requested is True
    assert intent.chart_type == "bar"


def test_graph_database_question_does_not_route_to_visualization():
    from sophyane.visualization_capability import (
        detect_visualization_intent,
    )

    intent = detect_visualization_intent(
        "what is a graph database?"
    )

    assert intent.requested is False


def test_matplotlib_explanation_is_not_visualization_intent():
    from sophyane.visualization_capability import (
        detect_visualization_intent,
    )

    intent = detect_visualization_intent(
        "explain matplotlib"
    )

    assert intent.requested is False


def test_extracts_grounded_label_value_points():
    from sophyane.visualization_capability import (
        extract_grounded_points,
    )

    points = extract_grounded_points(
        "make a graph: Jan: 10, Feb: 20, Mar: 15"
    )

    assert [
        point.label
        for point in points
    ] == [
        "Jan",
        "Feb",
        "Mar",
    ]

    assert [
        point.value
        for point in points
    ] == [
        10.0,
        20.0,
        15.0,
    ]


def test_unlabelled_numeric_sequence_is_grounded():
    from sophyane.visualization_capability import (
        extract_grounded_points,
    )

    points = extract_grounded_points(
        "plot 10, 20, 18, 35"
    )

    assert len(
        points
    ) == 4

    assert [
        point.value
        for point in points
    ] == [
        10.0,
        20.0,
        18.0,
        35.0,
    ]


def test_visualization_refuses_to_invent_missing_numbers(
    tmp_path,
):
    from sophyane.visualization_capability import (
        render_visualization,
    )

    result = render_visualization(
        request=(
            "make a graph comparing "
            "PRL NRL and ATRL"
        ),
        workspace=tmp_path,
    )

    assert result[
        "handled"
    ] is False

    assert (
        "no grounded numeric data"
        in str(
            result[
                "reason"
            ]
        )
    )


def test_renders_png_and_json_when_data_is_grounded(
    tmp_path,
):
    from pathlib import Path

    from sophyane.visualization_capability import (
        render_visualization,
    )

    result = render_visualization(
        request=(
            "show a line graph of monthly sales "
            "Jan: 10, Feb: 20, Mar: 15"
        ),
        workspace=tmp_path,
        title="Monthly sales",
    )

    assert result[
        "handled"
    ] is True

    png = Path(
        result[
            "png_path"
        ]
    )

    data = Path(
        result[
            "json_path"
        ]
    )

    assert png.is_file()
    assert png.stat().st_size > 0

    assert data.is_file()

    text = data.read_text(
        encoding="utf-8"
    )

    assert '"source": "user-grounded"' in text
    assert '"chart_type": "line"' in text


def test_user_response_exposes_artifact_paths(
    tmp_path,
):
    from sophyane.visualization_capability import (
        render_visualization,
        visualization_response_text,
    )

    result = render_visualization(
        request=(
            "bar chart A: 10, B: 20"
        ),
        workspace=tmp_path,
        title="Comparison",
    )

    response = visualization_response_text(
        result
    )

    assert "◆ Sophyane visualization" in response
    assert "Graph:" in response
    assert ".png" in response
    assert "Data:" in response
    assert ".json" in response


def test_adaptive_execution_exposes_visualization_fast_path(
    tmp_path,
):
    from sophyane.adaptive_execution import (
        try_visualization_intent,
    )

    result = try_visualization_intent(
        (
            "show a graph "
            "Jan: 10, Feb: 20"
        ),
        tmp_path,
    )

    assert result is not None

    assert (
        result[
            "capability"
        ]
        == "visualization"
    )

    assert result[
        "handled"
    ] is True

    assert ".png" in result[
        "response"
    ]


def test_visualization_fast_path_falls_back_when_data_missing(
    tmp_path,
):
    from sophyane.adaptive_execution import (
        try_visualization_intent,
    )

    result = try_visualization_intent(
        (
            "make a graph comparing "
            "PRL NRL and ATRL"
        ),
        tmp_path,
    )

    #
    # Intent exists but numbers are not grounded.
    # Normal Sophyane routing must get a chance to retrieve/extract them.
    #
    assert result is None
