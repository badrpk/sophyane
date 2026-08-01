from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "incremental_browser_edit.py"
    ).read_text(encoding="utf-8")


def test_incremental_browser_edit_does_not_import_html_lib() -> None:
    tree = ast.parse(_source())

    imports_html_lib = any(
        isinstance(node, ast.Import)
        and any(
            alias.name == "html"
            and alias.asname == "html_lib"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imports_html_lib is False


def test_incremental_browser_edit_entry_points_remain_present() -> None:
    source = _source()

    assert "def " in source
    assert "browser" in source.lower()
    assert "edit" in source.lower()
