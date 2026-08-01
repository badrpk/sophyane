from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "interactive_coding_doer.py"
    ).read_text(encoding="utf-8")


def test_interactive_coding_doer_does_not_import_json() -> None:
    tree = ast.parse(_source())

    imports_json = any(
        isinstance(node, ast.Import)
        and any(
            alias.name == "json"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imports_json is False


def test_interactive_coding_entry_points_remain_present() -> None:
    source = _source()

    assert "def " in source
    assert "coding" in source.lower()
    assert "interactive" in source.lower()
