from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "lc_compat"
        / "memory.py"
    ).read_text(encoding="utf-8")


def test_lc_compat_memory_does_not_import_any() -> None:
    tree = ast.parse(_source())

    imports_any = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "typing"
        and any(
            alias.name == "Any"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imports_any is False


def test_lc_compat_memory_entry_points_remain_present() -> None:
    tree = ast.parse(_source())

    names = {
        node.name
        for node in tree.body
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
            ),
        )
    }

    assert names
