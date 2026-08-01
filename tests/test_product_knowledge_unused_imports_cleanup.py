from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "cloud"
        / "product_knowledge.py"
    ).read_text(encoding="utf-8")


def test_product_knowledge_has_no_dead_re_or_any_imports() -> None:
    tree = ast.parse(_source())

    forbidden: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            forbidden.extend(
                alias.name
                for alias in node.names
                if alias.name == "re"
            )

        elif (
            isinstance(node, ast.ImportFrom)
            and node.module == "typing"
        ):
            forbidden.extend(
                f"typing.{alias.name}"
                for alias in node.names
                if alias.name == "Any"
            )

    assert forbidden == []


def test_product_knowledge_entry_points_remain_present() -> None:
    tree = ast.parse(_source())

    function_names = {
        node.name
        for node in tree.body
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef),
        )
    }

    expected = {'_match', 'channels_answer', 'inject_system_context', 'payment_methods_answer', 'plans_answer', 'product_answer'}

    assert expected <= function_names
