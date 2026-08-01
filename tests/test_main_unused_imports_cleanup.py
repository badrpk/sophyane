from __future__ import annotations

import ast
from pathlib import Path


def _main_source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "main.py"
    ).read_text(encoding="utf-8")


def test_main_does_not_import_unused_sys() -> None:
    tree = ast.parse(_main_source())

    imports_sys = any(
        isinstance(node, ast.Import)
        and any(
            alias.name == "sys"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imports_sys is False


def test_main_does_not_import_unused_tools_description() -> None:
    tree = ast.parse(_main_source())

    imports_tools_description = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "sophyane.tools"
        and any(
            alias.name == "tools_description"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imports_tools_description is False


def test_main_provider_factory_remains_present() -> None:
    source = _main_source()

    assert "def create_provider" in source
