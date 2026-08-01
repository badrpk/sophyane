from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).parents[1]


def _tree(relative_path: str) -> ast.Module:
    return ast.parse(
        (ROOT / relative_path).read_text(
            encoding="utf-8"
        )
    )


def test_snake_semantic_repair_does_not_import_any() -> None:
    tree = _tree(
        "src/sophyane/runtime_snake_semantic_repair.py"
    )

    imports_any = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "typing"
        and any(
            alias.name == "Any"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imports_any is False


def test_stagnation_patch_does_not_import_json() -> None:
    tree = _tree(
        "src/sophyane/runtime_stagnation_patch.py"
    )

    imports_json = any(
        isinstance(node, ast.Import)
        and any(
            alias.name == "json"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imports_json is False


def test_runtime_patch_definitions_remain() -> None:
    for relative_path in (
        "src/sophyane/runtime_snake_semantic_repair.py",
        "src/sophyane/runtime_stagnation_patch.py",
    ):
        tree = _tree(relative_path)

        definitions = [
            node.name
            for node in tree.body
            if isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.ClassDef,
                ),
            )
        ]

        assert definitions, relative_path
