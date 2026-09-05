from pathlib import Path


def test_csv_document_grounding_preserves_real_values(
    tmp_path: Path,
):
    from sophyane.document_grounding import (
        ground_document,
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
        ),
        encoding="utf-8",
    )

    document = ground_document(
        path
    )

    assert document.kind == "csv"
    assert "Jan, 120" in document.text
    assert "Feb, 160" in document.text
    assert document.source == "python.csv"


def test_json_document_grounding_preserves_real_values(
    tmp_path: Path,
):
    from sophyane.document_grounding import (
        ground_document,
    )

    path = (
        tmp_path
        / "production.json"
    )

    path.write_text(
        (
            '{"Q1": 275, '
            '"Q2": 310, '
            '"Q3": 298}'
        ),
        encoding="utf-8",
    )

    document = ground_document(
        path
    )

    assert document.kind == "json"
    assert "Q1: 275" in document.text
    assert "Q2: 310" in document.text


def test_document_reference_resolution_is_grounded(
    tmp_path: Path,
):
    from sophyane.document_grounding import (
        referenced_document_paths,
    )

    path = (
        tmp_path
        / "values.csv"
    )

    path.write_text(
        "name,value\nA,1\n",
        encoding="utf-8",
    )

    paths = referenced_document_paths(
        "graph values.csv",
        workspace=tmp_path,
    )

    assert paths == (
        path.resolve(),
    )


def test_missing_document_is_not_fabricated(
    tmp_path: Path,
):
    from sophyane.document_grounding import (
        ground_request_documents,
    )

    documents = ground_request_documents(
        "graph missing.csv",
        workspace=tmp_path,
    )

    assert documents == ()


def test_csv_graph_flows_into_existing_visual_dispatch(
    tmp_path: Path,
):
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

    result = try_general_visual_dispatch(
        "show a graph from sales.csv",
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


def test_json_graph_flows_into_existing_visual_dispatch(
    tmp_path: Path,
):
    from sophyane.visual_dispatch import (
        try_general_visual_dispatch,
    )

    path = (
        tmp_path
        / "production.json"
    )

    path.write_text(
        (
            '{"Q1": 275, '
            '"Q2": 310, '
            '"Q3": 298, '
            '"Q4": 355}'
        ),
        encoding="utf-8",
    )

    result = try_general_visual_dispatch(
        "make a chart from production.json",
        workspace=tmp_path,
    )

    assert result is not None
    assert result["handled"] is True
    assert result["route"] == "data_chart"


def test_import_document_without_graph_intent_does_not_force_visual(
    tmp_path: Path,
):
    from sophyane.visual_dispatch import (
        try_general_visual_dispatch,
    )

    path = (
        tmp_path
        / "sales.csv"
    )

    path.write_text(
        "month,sales\nJan,120\n",
        encoding="utf-8",
    )

    result = try_general_visual_dispatch(
        "import sales.csv",
        workspace=tmp_path,
    )

    assert result is None


def test_ungrounded_pdf_request_does_not_invent_content(
    tmp_path: Path,
):
    from sophyane.visual_dispatch import (
        try_general_visual_dispatch,
    )

    result = try_general_visual_dispatch(
        "make a chart from nonexistent.pdf",
        workspace=tmp_path,
    )

    assert result is None

    assert not list(
        tmp_path.rglob(
            "*.png"
        )
    )


def test_pdf_legacy_extractor_path_is_not_document_content(
    tmp_path,
    monkeypatch,
):
    import sophyane.document_grounding as grounding

    path = (
        tmp_path
        / "probe.pdf"
    )

    path.write_bytes(
        b"%PDF-1.4\n%%EOF\n"
    )

    monkeypatch.setattr(
        grounding,
        "_reuse_existing_pdf_extractor_unvalidated",
        lambda candidate: str(
            candidate.resolve()
        ),
    )

    result = (
        grounding
        ._reuse_existing_pdf_extractor(
            path
        )
    )

    assert result is None


def test_pdf_legacy_extractor_real_text_is_preserved(
    tmp_path,
    monkeypatch,
):
    import sophyane.document_grounding as grounding

    path = (
        tmp_path
        / "probe.pdf"
    )

    path.write_bytes(
        b"%PDF-1.4\n%%EOF\n"
    )

    grounded = (
        "Quarterly production report\n"
        "Q1 275\n"
        "Q2 310\n"
        "Q3 298\n"
        "Q4 355\n"
    )

    monkeypatch.setattr(
        grounding,
        "_reuse_existing_pdf_extractor_unvalidated",
        lambda candidate: grounded,
    )

    result = (
        grounding
        ._reuse_existing_pdf_extractor(
            path
        )
    )

    assert result == grounded
