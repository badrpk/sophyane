from __future__ import annotations

import ast
from pathlib import Path


def test_tui_v2_does_not_import_unused_asdict() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "tui_v2.py"
    ).read_text(encoding="utf-8")

    tree = ast.parse(source)

    imported_asdict = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "dataclasses"
        and any(
            alias.name == "asdict"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imported_asdict is False
