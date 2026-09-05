from pathlib import Path


def test_plain_csv_import_is_document_route(
    tmp_path: Path,
):
    from sophyane.document_dispatch import (
        try_general_document_dispatch,
    )

    source = (
        tmp_path
        / "sales.csv"
    )

    source.write_text(
        (
            "month,sales\n"
            "Jan,120\n"
            "Feb,160\n"
        ),
        encoding="utf-8",
    )

    result = try_general_document_dispatch(
        "import sales.csv",
        workspace=tmp_path,
    )

    assert result is not None
    assert result["handled"] is True
    assert result["route"] == "document_import"

    documents = result[
        "documents"
    ]

    assert len(documents) == 1
    assert documents[0].kind == "csv"
    assert "Jan, 120" in documents[0].text


def test_plain_json_import_is_not_visualization(
    tmp_path: Path,
):
    from sophyane.document_dispatch import (
        try_general_document_dispatch,
    )

    source = (
        tmp_path
        / "values.json"
    )

    source.write_text(
        '{"A": 10, "B": 20}',
        encoding="utf-8",
    )

    result = try_general_document_dispatch(
        "load values.json",
        workspace=tmp_path,
    )

    assert result is not None
    assert result["route"] == "document_import"


def test_graph_request_is_not_stolen_by_document_import(
    tmp_path: Path,
):
    from sophyane.document_dispatch import (
        try_general_document_dispatch,
    )

    source = (
        tmp_path
        / "values.csv"
    )

    source.write_text(
        "name,value\nA,10\nB,20\n",
        encoding="utf-8",
    )

    assert (
        try_general_document_dispatch(
            "make a graph from values.csv",
            workspace=tmp_path,
        )
        is None
    )


def test_graph_request_still_uses_visual_dispatch(
    tmp_path: Path,
):
    from sophyane.visual_dispatch import (
        try_general_visual_dispatch,
    )

    source = (
        tmp_path
        / "values.csv"
    )

    source.write_text(
        "name,value\nA,10\nB,20\n",
        encoding="utf-8",
    )

    result = try_general_visual_dispatch(
        "make a graph from values.csv",
        workspace=tmp_path,
    )

    assert result is not None
    assert result["handled"] is True
    assert result["route"] == "data_chart"


def test_missing_import_file_falls_through(
    tmp_path: Path,
):
    from sophyane.document_dispatch import (
        try_general_document_dispatch,
    )

    result = try_general_document_dispatch(
        "import missing.pdf",
        workspace=tmp_path,
    )

    assert result is None


def test_document_import_remembers_latest_grounded_document(
    tmp_path,
):
    from sophyane.document_dispatch import (
        try_general_document_dispatch,
    )

    from sophyane.document_session_context import (
        clear_current_document,
        current_document,
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

    result = (
        try_general_document_dispatch(
            "import sales.csv",
            workspace=tmp_path,
        )
    )

    assert result is not None
    assert result["handled"] is True

    current = (
        current_document()
    )

    assert current is not None
    assert current.path == str(
        path.resolve()
    )

    assert "Jan" in current.text
    assert "120" in current.text
