from sophyane.artifact_extractor import extract_artifact, merge_continuation


def test_extracts_html_from_structured_action_content():
    raw = '{"action":{"type":"update_html","content":"<!doctype html><html><body>ok</body></html>"}}'
    artifact = extract_artifact(raw)
    assert artifact is not None
    assert artifact.complete is True
    assert artifact.source.endswith("content")
    assert artifact.content.startswith("<!doctype html>")


def test_extracts_markdown_html():
    artifact = extract_artifact("```html\n<!doctype html><html><body>x</body></html>\n```")
    assert artifact is not None
    assert artifact.complete is True


def test_recovers_truncated_json_embedded_html():
    raw = '{"action":{"type":"update_html","content":"<!doctype html><html><script>const x = 1;'
    artifact = extract_artifact(raw)
    assert artifact is not None
    assert artifact.complete is False
    assert "const x = 1" in artifact.content


def test_merges_continuation_without_duplicate_overlap():
    combined = merge_continuation("<!doctype html><html><body>hello", "hello world</body></html>")
    assert combined == "<!doctype html><html><body>hello world</body></html>"
