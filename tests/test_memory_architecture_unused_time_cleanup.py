from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "memory_architecture.py"
    ).read_text(encoding="utf-8")


def test_memory_architecture_does_not_import_time() -> None:
    tree = ast.parse(_source())

    imports_time = any(
        isinstance(node, ast.Import)
        and any(
            alias.name == "time"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imports_time is False


def test_memory_architecture_entry_points_remain_present() -> None:
    source = _source()

    assert "def " in source
    assert "memory" in source.lower()
    assert "sqlite" in source.lower() or "database" in source.lower()
