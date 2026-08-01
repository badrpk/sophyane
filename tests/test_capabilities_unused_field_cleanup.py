from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "capabilities.py"
    ).read_text(encoding="utf-8")


def test_capabilities_does_not_import_unused_field() -> None:
    tree = ast.parse(_source())

    imports_field = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "dataclasses"
        and any(
            alias.name == "field"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imports_field is False


def test_capability_definitions_remain_present() -> None:
    source = _source()

    assert "class " in source
    assert "capabil" in source.lower()
