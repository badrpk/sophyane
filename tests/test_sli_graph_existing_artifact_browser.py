from __future__ import annotations

from pathlib import Path

import sophyane.browser_runtime_v2 as browser_runtime
import sophyane.sli_graph as sli_graph


def test_existing_browser_request_classifier():
    positive = (
        "open this in browser",
        "open it",
        "preview this",
        "show this in browser",
        "reopen it",
    )

    for request in positive:
        assert sli_graph._existing_artifact_browser_request(
            request
        )


def test_unrelated_open_request_does_not_match():
    negative = (
        "open source software",
        "show cats website examples",
        "make cats website",
        "search browser history",
    )

    for request in negative:
        assert not sli_graph._existing_artifact_browser_request(
            request
        )


def test_browser_followup_bypasses_classification_and_acquisition(
    tmp_path: Path,
    monkeypatch,
):
    artifact = tmp_path / "index.html"
    artifact.write_text(
        "<!doctype html><html><body>"
        "<h1>Cats</h1>"
        "<p>Existing verified project.</p>"
        "</body></html>",
        encoding="utf-8",
    )

    def forbidden_classify(*args, **kwargs):
        raise AssertionError(
            "classify must not execute for browser follow-up"
        )

    monkeypatch.setattr(
        sli_graph,
        "classify",
        forbidden_classify,
    )

    calls = []

    def fake_open(workspace, progress):
        calls.append(Path(workspace))
        return (
            True,
            "Browser command accepted for test.",
        )

    monkeypatch.setattr(
        browser_runtime,
        "open_verified_browser",
        fake_open,
    )

    result = sli_graph.run_sli_graph(
        "open this in browser",
        workspace=tmp_path,
    )

    assert result.success is True
    assert result.route == "existing_artifact_browser"
    assert result.files == ["index.html"]
    assert result.promoted is False
    assert result.chunks_added == 0
    assert calls == [tmp_path.resolve()]
    assert "Internet acquisition used: False" in result.report
    assert "LLM used: False" in result.report


def test_missing_existing_artifact_fails_without_acquisition(
    tmp_path: Path,
    monkeypatch,
):
    def forbidden_classify(*args, **kwargs):
        raise AssertionError(
            "classification/acquisition must not execute"
        )

    monkeypatch.setattr(
        sli_graph,
        "classify",
        forbidden_classify,
    )

    result = sli_graph.run_sli_graph(
        "open this in browser",
        workspace=tmp_path,
    )

    assert result.success is False
    assert result.route == "existing_artifact_browser"
    assert "no index.html" in result.report.lower()
    assert "Internet acquisition used: False" in result.report
