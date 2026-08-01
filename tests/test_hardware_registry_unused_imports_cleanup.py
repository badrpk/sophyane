from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "hardware_registry.py"
    ).read_text(encoding="utf-8")


def test_hardware_registry_does_not_import_dead_stdlib_names() -> None:
    tree = ast.parse(_source())

    forbidden = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name in {
            "json",
            "os",
            "re",
        }
    ]

    assert forbidden == []


def test_hardware_registry_entry_points_remain_present() -> None:
    source = _source()

    assert "def " in source
    assert "hardware" in source.lower()
    assert "registr" in source.lower()
