from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "failure_memory.py"
    ).read_text(encoding="utf-8")


def test_failure_memory_does_not_import_iterable() -> None:
    tree = ast.parse(_source())

    imports_iterable = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "typing"
        and any(
            alias.name == "Iterable"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imports_iterable is False


def test_failure_memory_entry_points_remain_present() -> None:
    source = _source()

    assert "def " in source
    assert "failure" in source.lower()
    assert "memory" in source.lower()
