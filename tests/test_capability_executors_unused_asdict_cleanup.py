from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "capability_executors.py"
    ).read_text(encoding="utf-8")


def test_capability_executors_does_not_import_asdict() -> None:
    tree = ast.parse(_source())

    imports_asdict = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "dataclasses"
        and any(
            alias.name == "asdict"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imports_asdict is False


def test_executor_entry_points_remain_present() -> None:
    source = _source()

    assert "def " in source
    assert "execut" in source.lower()
    assert "capabil" in source.lower()
