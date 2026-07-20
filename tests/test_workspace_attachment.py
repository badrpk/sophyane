from pathlib import Path

from sophyane.workspace_attachment import _looks_like_project, extract_embedded_html


def test_extracts_html_from_artifact_envelope():
    raw = '{"selected_index":0,"action":{"type":"FILE_ARTIFACT","content":"<!doctype html><html><body><h1>Quiz</h1></body></html>"}}'
    html = extract_embedded_html(raw)
    assert html is not None
    assert html.startswith("<!doctype html>")
    assert "selected_index" not in html
    assert html.count("<html") == 1


def test_extracts_html_from_mixed_multiple_json_objects():
    raw = 'note {"content":"<!doctype html><html><body>One</body></html>"} trailing {"x":1}'
    html = extract_embedded_html(raw)
    assert html is not None
    assert "One" in html
    assert "trailing" not in html


def test_project_directory_detection(tmp_path: Path):
    assert not _looks_like_project(tmp_path)
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")
    assert _looks_like_project(tmp_path)
