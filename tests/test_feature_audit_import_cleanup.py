from __future__ import annotations

import ast
from pathlib import Path


def _tree() -> ast.Module:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "feature_audit.py"
    ).read_text(encoding="utf-8")

    return ast.parse(source)


def test_feature_audit_has_one_path_import() -> None:
    path_imports = [
        node.lineno
        for node in ast.walk(_tree())
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "pathlib"
            and any(
                alias.name == "Path"
                for alias in node.names
            )
        )
    ]

    assert len(path_imports) == 1


def test_feature_audit_removes_confirmed_dead_imports() -> None:
    forbidden: list[str] = []

    for node in ast.walk(_tree()):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {
                    "json",
                    "urllib.request",
                }:
                    forbidden.append(alias.name)

        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if (
                    node.module == "dataclasses"
                    and alias.name == "field"
                ):
                    forbidden.append("dataclasses.field")

                if (
                    node.module == "urllib"
                    and alias.name == "request"
                ):
                    forbidden.append("urllib.request")

    assert forbidden == []


def test_feature_audit_still_uses_path() -> None:
    path_loads = [
        node.lineno
        for node in ast.walk(_tree())
        if (
            isinstance(node, ast.Name)
            and node.id == "Path"
            and isinstance(node.ctx, ast.Load)
        )
    ]

    assert path_loads
