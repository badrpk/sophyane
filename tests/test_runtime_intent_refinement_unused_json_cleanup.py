from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "runtime_intent_refinement_patch.py"
    ).read_text(encoding="utf-8")


def test_runtime_intent_refinement_patch_does_not_import_json() -> None:
    tree = ast.parse(_source())

    imports_json = any(
        isinstance(node, ast.Import)
        and any(
            alias.name == "json"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imports_json is False


def test_runtime_intent_refinement_entry_points_remain_present() -> None:
    source = _source()

    assert "def " in source
    assert "intent" in source.lower()
    assert "refin" in source.lower()
