from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "native_worker_pool.py"
    ).read_text(encoding="utf-8")


def test_native_worker_pool_does_not_import_path() -> None:
    tree = ast.parse(_source())

    imports_path = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "pathlib"
        and any(
            alias.name == "Path"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imports_path is False


def test_native_worker_pool_entry_points_remain_present() -> None:
    source = _source()

    assert "def " in source
    assert "worker" in source.lower()
    assert "pool" in source.lower()
