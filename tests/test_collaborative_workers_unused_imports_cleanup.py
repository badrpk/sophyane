from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "collaborative_workers.py"
    ).read_text(encoding="utf-8")


def test_collaborative_workers_has_no_dead_json_or_urllib_imports() -> None:
    tree = ast.parse(_source())

    forbidden: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {
                    "json",
                    "urllib.request",
                }:
                    forbidden.append(alias.name)

        elif isinstance(node, ast.ImportFrom):
            if node.module == "urllib":
                for alias in node.names:
                    if alias.name == "request":
                        forbidden.append("urllib.request")

    assert forbidden == []


def test_collaborative_worker_entry_points_remain_present() -> None:
    source = _source()

    assert "def run_combined" in source
    assert "Combined workers" in source
    assert "combined_summary" in source
