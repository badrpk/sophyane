from __future__ import annotations

import ast
from pathlib import Path


def test_primary_snippet_is_assigned_before_comparison() -> None:
    source_path = (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "cloud"
        / "portal.py"
    )
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    assignments = []
    loads = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "primary_snip":
            if isinstance(node.ctx, ast.Store):
                assignments.append(node.lineno)
            elif isinstance(node.ctx, ast.Load):
                loads.append(node.lineno)

    assert assignments, "primary_snip must have an explicit assignment"
    assert loads, "primary_snip should still be used by the comparison logic"
    assert min(assignments) < min(loads)


def test_primary_snippet_has_grounded_fallback() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "cloud"
        / "portal.py"
    ).read_text(encoding="utf-8")

    assert 'primary_result.get("snippet")' in source
    assert 'primary_result.get("content")' in source
    assert "or grounded" in source
