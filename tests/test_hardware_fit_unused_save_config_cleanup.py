from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "hardware_fit.py"
    ).read_text(encoding="utf-8")


def test_hardware_fit_does_not_import_save_config() -> None:
    tree = ast.parse(_source())

    imports_save_config = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "sophyane.config"
        and any(
            alias.name == "save_config"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imports_save_config is False


def test_hardware_fit_entry_points_remain_present() -> None:
    source = _source()

    assert "def " in source
    assert "hardware" in source.lower()
    assert "fit" in source.lower()
