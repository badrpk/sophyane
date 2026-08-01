from __future__ import annotations

import ast
from pathlib import Path


def test_platform_probe_has_no_placeholder_free_fstrings() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "platform_probe.py"
    ).read_text(encoding="utf-8")

    tree = ast.parse(source)

    empty_fstrings = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue

        has_placeholder = any(
            isinstance(child, ast.FormattedValue)
            for child in ast.walk(node)
        )

        if not has_placeholder:
            empty_fstrings.append(node.lineno)

    assert empty_fstrings == []
