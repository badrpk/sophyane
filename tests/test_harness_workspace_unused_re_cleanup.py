from __future__ import annotations

import ast
from pathlib import Path


def test_harness_workspace_does_not_import_unused_re() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "harness_workspace.py"
    ).read_text(encoding="utf-8")

    tree = ast.parse(source)

    plain_re_imports = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        and any(
            alias.name == "re"
            for alias in node.names
        )
    ]

    assert plain_re_imports == []


def test_workspace_isolation_functions_remain_present() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "harness_workspace.py"
    ).read_text(encoding="utf-8")

    assert "def is_new_project_request" in source
    assert "def select_workspace" in source
