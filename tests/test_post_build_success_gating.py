from pathlib import Path

from sophyane.tui import _artifact_snapshot, _execution_succeeded


def test_failed_execution_never_opens_success_menu(tmp_path: Path) -> None:
    index = tmp_path / "index.html"
    index.write_text("<html><body>old</body></html>", encoding="utf-8")
    before = _artifact_snapshot(tmp_path)
    (tmp_path / ".sophyane-partial-index.html").write_text("broken", encoding="utf-8")
    result = "Execution stopped safely: provider could not produce a usable artifact."
    assert not _execution_succeeded(result, before, tmp_path)


def test_unchanged_old_artifact_is_not_current_success(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html><body>old</body></html>", encoding="utf-8")
    before = _artifact_snapshot(tmp_path)
    assert not _execution_succeeded("Completed.", before, tmp_path)


def test_changed_artifact_with_positive_result_is_success(tmp_path: Path) -> None:
    index = tmp_path / "index.html"
    index.write_text("<html><body>old</body></html>", encoding="utf-8")
    before = _artifact_snapshot(tmp_path)
    index.write_text("<html><body>new application</body></html>", encoding="utf-8")
    assert _execution_succeeded("Updated and opened the browser project.", before, tmp_path)


def test_partial_and_server_logs_do_not_count_as_success(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html><body>old</body></html>", encoding="utf-8")
    before = _artifact_snapshot(tmp_path)
    (tmp_path / ".sophyane-partial-index.html").write_text("larger broken output", encoding="utf-8")
    (tmp_path / "server-1234.log").write_text("GET /index.html 200", encoding="utf-8")
    assert not _execution_succeeded("Completed.", before, tmp_path)
