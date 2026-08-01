from __future__ import annotations

import ast
from pathlib import Path


def test_mobile_filesystem_test_has_no_dead_original_home() -> None:
    source = (
        Path(__file__).parents[1]
        / "tests"
        / "test_tui_mobile_filesystem.py"
    ).read_text(encoding="utf-8")

    tree = ast.parse(source)

    original_home_names = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and node.id == "original_home"
    ]

    assert original_home_names == []


def test_mobile_filesystem_tests_remain_present() -> None:
    source = (
        Path(__file__).parents[1]
        / "tests"
        / "test_tui_mobile_filesystem.py"
    ).read_text(encoding="utf-8")

    assert "def test_" in source
    assert "filesystem" in source.lower() or "file" in source.lower()
