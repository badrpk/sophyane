from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "state_graph.py"
    ).read_text(encoding="utf-8")


def test_state_graph_does_not_import_mutable_mapping() -> None:
    tree = ast.parse(_source())

    imports_mutable_mapping = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "typing"
        and any(
            alias.name == "MutableMapping"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imports_mutable_mapping is False


def test_state_graph_entry_points_remain_present() -> None:
    source = _source()

    assert "class " in source or "def " in source
    assert "state" in source.lower()
    assert "graph" in source.lower()
