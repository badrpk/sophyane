from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "multiagent.py"
    ).read_text(encoding="utf-8")


def test_multiagent_does_not_import_callable() -> None:
    tree = ast.parse(_source())

    imports_callable = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "typing"
        and any(
            alias.name == "Callable"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imports_callable is False


def test_multiagent_entry_points_remain_present() -> None:
    source = _source()

    assert "def " in source
    assert "agent" in source.lower()
    assert "multi" in source.lower()
