from __future__ import annotations

import ast
from pathlib import Path


def test_local_runtime_has_no_dead_lib_dir_local() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "local_runtime.py"
    ).read_text(encoding="utf-8")

    tree = ast.parse(source)

    names = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and node.id == "lib_dir"
    ]

    assert names == []


def test_local_runtime_core_entry_points_remain() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "local_runtime.py"
    ).read_text(encoding="utf-8")

    # Guard against accidental broad deletion.
    assert "def " in source
    assert "subprocess" in source or "Path" in source
