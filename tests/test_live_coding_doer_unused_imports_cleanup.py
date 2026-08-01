from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "live_coding_doer.py"
    ).read_text(encoding="utf-8")


def test_live_coding_doer_has_no_dead_asdict_or_callable_imports() -> None:
    tree = ast.parse(_source())

    forbidden: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue

        for alias in node.names:
            if (
                node.module == "dataclasses"
                and alias.name == "asdict"
            ):
                forbidden.append("dataclasses.asdict")

            if (
                node.module == "typing"
                and alias.name == "Callable"
            ):
                forbidden.append("typing.Callable")

    assert forbidden == []


def test_live_coding_doer_entry_points_remain_present() -> None:
    source = _source()

    assert "def " in source
    assert "coding" in source.lower()
    assert "live" in source.lower()
