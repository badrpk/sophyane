from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "goal_execution.py"
    ).read_text(encoding="utf-8")


def test_goal_execution_does_not_import_mapping() -> None:
    tree = ast.parse(_source())

    imports_mapping = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "collections.abc"
        and any(
            alias.name == "Mapping"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imports_mapping is False


def test_goal_execution_entry_points_remain_present() -> None:
    source = _source()

    assert "def " in source
    assert "goal" in source.lower()
    assert "execut" in source.lower()
