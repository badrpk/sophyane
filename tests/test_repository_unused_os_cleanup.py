from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "repository.py"
    ).read_text(encoding="utf-8")


def test_repository_does_not_import_os() -> None:
    tree = ast.parse(_source())

    imports_os = any(
        isinstance(node, ast.Import)
        and any(
            alias.name == "os"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imports_os is False


def test_repository_entry_points_remain_present() -> None:
    source = _source()

    assert "def " in source
    assert "repository" in source.lower()
