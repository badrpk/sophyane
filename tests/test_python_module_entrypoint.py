from __future__ import annotations

import ast
from pathlib import Path


def test_python_module_entrypoint_uses_canonical_cli_entry():
    path = Path(
        "src/sophyane/__main__.py"
    )

    text = path.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(text)

    imports = [
        (
            node.module,
            tuple(
                alias.name
                for alias in node.names
            ),
        )
        for node in tree.body
        if isinstance(
            node,
            ast.ImportFrom,
        )
    ]

    assert (
        "sophyane.cli_entry",
        ("main",),
    ) in imports

    assert (
        "sophyane.main",
        ("main",),
    ) not in imports

    assert (
        "main",
        ("main",),
    ) not in imports


def test_legacy_main_has_unconditional_prompt_success_contract():
    """Document why repository execution must not enter legacy main."""

    path = Path(
        "src/sophyane/main.py"
    )

    text = path.read_text(
        encoding="utf-8"
    )

    # This is deliberately a characterization assertion.
    #
    # When this legacy compatibility surface is eventually removed or
    # corrected, this test should be updated with that change.
    assert 'if args.prompt:' in text
    assert 'response = agent.ask(" ".join(args.prompt))' in text
