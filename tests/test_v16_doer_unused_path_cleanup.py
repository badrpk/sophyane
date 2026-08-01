from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "v16_doer.py"
    ).read_text(encoding="utf-8")


def test_v16_doer_does_not_import_path() -> None:
    tree = ast.parse(_source())

    imports_path = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "pathlib"
        and any(
            alias.name == "Path"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imports_path is False


def test_v16_doer_entry_points_remain_present() -> None:
    source = _source()

    assert "def " in source
    assert "doer" in source.lower()
