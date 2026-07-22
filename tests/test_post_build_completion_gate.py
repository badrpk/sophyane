from pathlib import Path

from sophyane.post_build_menu import (
    PostBuildMenu,
    detect_entry_file,
    verify_completion,
)


def test_arbitrary_file_is_not_an_entry(tmp_path: Path) -> None:
    (tmp_path / "validate_and_repair.py").write_text(
        "print('validator')\n",
        encoding="utf-8",
    )
    (tmp_path / "provider-response.txt").write_text(
        "model output",
        encoding="utf-8",
    )

    assert detect_entry_file(tmp_path) is None
    evidence = verify_completion(tmp_path)
    assert evidence.complete is False
    assert evidence.entry is None


def test_valid_html_is_complete(tmp_path: Path) -> None:
    index = tmp_path / "index.html"
    index.write_text(
        "<!doctype html><html><body><h1>Ready</h1></body></html>",
        encoding="utf-8",
    )

    evidence = verify_completion(tmp_path)
    assert evidence.complete is True
    assert evidence.entry == index
    assert evidence.project_type == "browser"


def test_incomplete_html_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(
        "<h1>Missing document structure</h1>",
        encoding="utf-8",
    )

    evidence = verify_completion(tmp_path)
    assert evidence.complete is False
    assert any("HTML" in error for error in evidence.errors)


def test_invalid_python_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text(
        "def broken(:\n    pass\n",
        encoding="utf-8",
    )

    evidence = verify_completion(tmp_path)
    assert evidence.complete is False
    assert any("syntax error" in error.lower() for error in evidence.errors)


def test_menu_withholds_success_for_missing_entry(tmp_path: Path) -> None:
    messages: list[str] = []
    (tmp_path / "test_file.txt").write_text("not an app", encoding="utf-8")

    menu = PostBuildMenu(
        tmp_path,
        input_fn=lambda _: "0",
        output_fn=messages.append,
    )

    # Simulate an interactive terminal for this unit test by validating directly.
    evidence = menu.completion_evidence()
    assert evidence.complete is False
