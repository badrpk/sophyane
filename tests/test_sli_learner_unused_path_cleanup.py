from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "sli_learner.py"
    ).read_text(encoding="utf-8")


def test_sli_learner_does_not_import_path() -> None:
    tree = ast.parse(_source())

    imports_path = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "pathlib"
        and any(
            alias.name == "Path"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imports_path is False


def test_sli_learner_entry_points_remain_present() -> None:
    source = _source()

    assert "def " in source
    assert "sli" in source.lower()
    assert "learn" in source.lower()
