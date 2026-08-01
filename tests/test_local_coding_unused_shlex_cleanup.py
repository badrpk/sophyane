from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "local_coding_capability.py"
    ).read_text(encoding="utf-8")


def test_local_coding_capability_does_not_import_shlex() -> None:
    tree = ast.parse(_source())

    imports_shlex = any(
        isinstance(node, ast.Import)
        and any(
            alias.name == "shlex"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imports_shlex is False


def test_local_coding_capability_entry_points_remain() -> None:
    source = _source()

    # Guard against accidental broad deletion.
    assert "def " in source
    assert "local" in source.lower()
    assert "coding" in source.lower()
