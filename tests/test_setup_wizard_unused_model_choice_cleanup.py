from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "setup_wizard.py"
    ).read_text(encoding="utf-8")


def test_setup_wizard_does_not_import_model_choice() -> None:
    tree = ast.parse(_source())

    imports_model_choice = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "sophyane.model_catalog"
        and any(
            alias.name == "ModelChoice"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imports_model_choice is False


def test_setup_wizard_entry_points_remain_present() -> None:
    source = _source()

    assert "def " in source
    assert "setup" in source.lower()
    assert "wizard" in source.lower()
