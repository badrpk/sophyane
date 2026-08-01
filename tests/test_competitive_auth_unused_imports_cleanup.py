from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "competitive"
        / "auth.py"
    ).read_text(encoding="utf-8")


def test_competitive_auth_has_no_dead_imports() -> None:
    tree = ast.parse(_source())

    forbidden: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue

        for alias in node.names:
            if (
                node.module == "typing"
                and alias.name == "Any"
            ):
                forbidden.append("typing.Any")

            if (
                node.module == "urllib.error"
                and alias.name in {
                    "URLError",
                    "HTTPError",
                }
            ):
                forbidden.append(
                    f"urllib.error.{alias.name}"
                )

    assert forbidden == []


def test_competitive_auth_entry_points_remain_present() -> None:
    tree = ast.parse(_source())

    names = {
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
    }

    assert names
