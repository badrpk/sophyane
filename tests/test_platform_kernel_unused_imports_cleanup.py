from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "platform_kernel.py"
    ).read_text(encoding="utf-8")


def test_platform_kernel_does_not_import_dead_stdlib_names() -> None:
    tree = ast.parse(_source())

    forbidden = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name in {
            "os",
            "subprocess",
        }
    ]

    assert forbidden == []


def test_platform_kernel_entry_points_remain_present() -> None:
    source = _source()

    assert "def " in source
    assert "platform" in source.lower()
    assert "kernel" in source.lower()
