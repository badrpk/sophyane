from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "competitive"
        / "payments.py"
    ).read_text(encoding="utf-8")


def test_competitive_payments_does_not_import_hashlib() -> None:
    tree = ast.parse(_source())

    imports_hashlib = any(
        isinstance(node, ast.Import)
        and any(
            alias.name == "hashlib"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imports_hashlib is False


def test_competitive_payments_entry_points_remain_present() -> None:
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
