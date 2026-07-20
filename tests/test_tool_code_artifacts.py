from pathlib import Path

from sophyane.browser_partial_recovery import _save_raw
from sophyane.workspace_attachment import extract_embedded_html, extract_embedded_partial_html


HTML = "<!doctype html><html><body><script>const x=1;</script></body></html>"


def test_extracts_complete_html_from_tool_code_json() -> None:
    raw = '{"action":{"type":"tool_code","tool_code":' + repr(HTML).replace("'", '"') + '}}'
    # Build valid JSON safely because the HTML contains no double quotes in this fixture.
    assert extract_embedded_html(raw) == HTML


def test_extracts_partial_html_from_truncated_tool_code_json() -> None:
    raw = '{"action":{"type":"tool_code","tool_code":"<!doctype html>\\n<html>\\n<body>\\n<script>const x=1;'
    partial = extract_embedded_partial_html(raw)
    assert partial is not None
    assert partial.startswith("<!doctype html>")
    assert "\n<html>" in partial


def test_raw_evidence_paths_do_not_overwrite_across_runs(tmp_path: Path) -> None:
    first = _save_raw(tmp_path, "20260720-234000-000000001", 1, "first")
    second = _save_raw(tmp_path, "20260720-234100-000000002", 1, "second")
    assert first != second
    assert first.read_text(encoding="utf-8") == "first"
    assert second.read_text(encoding="utf-8") == "second"
