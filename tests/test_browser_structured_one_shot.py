from types import SimpleNamespace

from sophyane import adaptive_execution as adaptive


def _html():
    body = "A" * 400
    return (
        "<!doctype html><html><body>"
        f"<main>{body}</main>"
        "<script>"
        "const $=s=>document.querySelector(s);"
        "document.body.dataset.ready='1';"
        "</script>"
        "</body></html>"
    )


def test_one_shot_accepts_malformed_nifdu_structured_index_write(
    tmp_path,
    monkeypatch,
):
    html = _html()

    # Deliberately invalid JSON: the HTML contains unescaped double quotes.
    # execution_runtime's quasi-JSON file recovery must reconstruct it.
    raw = (
        '{"type":"write_file","path":"index.html","content":"'
        + html
        + '"}'
    )

    opened = []

    monkeypatch.setattr(
        "sophyane.execution_runtime.execute_action",
        lambda action, workspace, progress: (
            opened.append(action) or True,
            "opened",
        ),
    )

    result = adaptive._one_shot_browser_artifact(
        ask=lambda prompt: SimpleNamespace(text=raw),
        original_request="build a polished responsive website",
        workspace=tmp_path,
        progress=lambda message: None,
    )

    target = tmp_path / "index.html"

    assert result is not None
    assert target.read_text(encoding="utf-8") == html
    assert opened == [{"type": "open_browser"}]


def test_one_shot_does_not_accept_append_as_complete_artifact(
    tmp_path,
    monkeypatch,
):
    html = _html()

    raw = (
        '{"type":"append_file","path":"index.html","content":"'
        + html
        + '"}'
    )

    monkeypatch.setattr(
        "sophyane.execution_runtime.execute_action",
        lambda action, workspace, progress: (True, "opened"),
    )

    result = adaptive._one_shot_browser_artifact(
        ask=lambda prompt: SimpleNamespace(text=raw),
        original_request="build a polished responsive website",
        workspace=tmp_path,
        progress=lambda message: None,
    )

    assert result is None
    assert not (tmp_path / "index.html").exists()
