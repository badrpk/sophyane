from __future__ import annotations

import ast
from pathlib import Path


def test_task_execution_does_not_import_unused_sys() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "task_execution.py"
    ).read_text(encoding="utf-8")

    tree = ast.parse(source)

    imports_sys = any(
        isinstance(node, ast.Import)
        and any(
            alias.name == "sys"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imports_sys is False
