from __future__ import annotations

import ast
from pathlib import Path


def _portal_tree() -> ast.Module:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "cloud"
        / "portal.py"
    ).read_text(encoding="utf-8")

    return ast.parse(source)


def test_portal_does_not_import_unused_os() -> None:
    imports_os = any(
        isinstance(node, ast.Import)
        and any(
            alias.name == "os"
            for alias in node.names
        )
        for node in ast.walk(_portal_tree())
    )

    assert imports_os is False


def test_portal_does_not_import_unused_parse_qs() -> None:
    imports_parse_qs = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "urllib.parse"
        and any(
            alias.name == "parse_qs"
            for alias in node.names
        )
        for node in ast.walk(_portal_tree())
    )

    assert imports_parse_qs is False
