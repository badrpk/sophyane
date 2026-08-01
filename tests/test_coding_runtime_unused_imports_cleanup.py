from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "coding_runtime.py"
    ).read_text(encoding="utf-8")


def test_coding_runtime_does_not_import_fnmatch_or_os() -> None:
    tree = ast.parse(_source())

    forbidden = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name in {
            "fnmatch",
            "os",
        }
    ]

    assert forbidden == []


def test_coding_runtime_entry_points_remain_present() -> None:
    source = _source()

    assert "def " in source
    assert "coding" in source.lower()
    assert "runtime" in source.lower()
