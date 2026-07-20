from __future__ import annotations

from pathlib import Path

from sophyane.post_build_menu import (
    PostBuildMenu,
    ProjectServer,
    detect_entry_file,
    normalize_choice,
    render_menu,
)


def test_menu_rendering_contains_all_choices() -> None:
    menu = render_menu()
    for number in range(10):
        assert f"{number}." in menu
    assert "Press Enter to open in browser" in menu


def test_input_routing_accepts_numbers_commands_and_default() -> None:
    assert normalize_choice("") == "1"
    assert normalize_choice("browser") == "1"
    assert normalize_choice("bash") == "2"
    assert normalize_choice("status") == "7"
    assert normalize_choice("new") == "9"
    assert normalize_choice("exit") == "0"
    assert normalize_choice("10") is None
    assert normalize_choice("unknown") is None


def test_entry_detection_prefers_browser_entry(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("print('ok')", encoding="utf-8")
    (tmp_path / "index.html").write_text("<h1>ok</h1>", encoding="utf-8")
    assert detect_entry_file(tmp_path) == tmp_path / "index.html"


def test_server_reuse_and_http_verification(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<!doctype html><title>ok</title>", encoding="utf-8")
    server = ProjectServer(tmp_path)
    first = server.start()
    second = server.start()
    try:
        assert first == second
        assert server.healthy()
    finally:
        server.stop()


def test_menu_preserves_workspace_when_starting_new_project(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "index.html"
    entry.write_text("<h1>kept</h1>", encoding="utf-8")
    outputs: list[str] = []
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    menu = PostBuildMenu(tmp_path, input_fn=lambda _: "9", output_fn=outputs.append)
    assert menu.run() == "new"
    assert entry.read_text(encoding="utf-8") == "<h1>kept</h1>"
    assert any("preserved" in line.lower() for line in outputs)


def test_invalid_input_is_handled_then_exit(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "index.html").write_text("<h1>ok</h1>", encoding="utf-8")
    choices = iter(["invalid", "0"])
    outputs: list[str] = []
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    menu = PostBuildMenu(tmp_path, input_fn=lambda _: next(choices), output_fn=outputs.append)
    assert menu.run() == "exit"
    assert "Please choose a number from 0 to 9." in outputs


def test_export_verifies_zip(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>ok</h1>", encoding="utf-8")
    outputs: list[str] = []
    menu = PostBuildMenu(tmp_path, output_fn=outputs.append)
    menu.export_project()
    exported = tmp_path.parent / f"{tmp_path.name}.zip"
    assert exported.is_file()
    assert exported.stat().st_size > 0
