from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "hardware_api.py"
    ).read_text(encoding="utf-8")


def test_hardware_api_does_not_import_edge_system_prompt() -> None:
    tree = ast.parse(_source())

    imports_prompt = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "sophyane.edge_agent"
        and any(
            alias.name == "EDGE_SYSTEM_PROMPT"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imports_prompt is False


def test_hardware_api_entry_points_remain_present() -> None:
    source = _source()

    assert "def " in source
    assert "hardware" in source.lower()
    assert "api" in source.lower()
