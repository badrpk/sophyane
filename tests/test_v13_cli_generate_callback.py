from __future__ import annotations

import ast
from pathlib import Path


def test_v13_cli_has_no_generate_redefinition_pattern() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "v13_cli.py"
    ).read_text(encoding="utf-8")

    tree = ast.parse(source)

    plain_generate_assignments = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "generate"
            for target in node.targets
        )
    ]

    nested_generate_definitions = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "generate"
    ]

    assert plain_generate_assignments == []
    assert nested_generate_definitions == []


def test_v13_cli_uses_explicit_provider_callback() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "v13_cli.py"
    ).read_text(encoding="utf-8")

    assert "generate_callback" in source
    assert "def provider_generate" in source
    assert "generate=generate_callback" in source
