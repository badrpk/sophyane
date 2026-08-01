from __future__ import annotations

import ast
import builtins
from pathlib import Path

from sophyane import request_intercepts


def test_only_one_public_input_capture_installer_exists() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "request_intercepts.py"
    ).read_text(encoding="utf-8")

    tree = ast.parse(source)

    definitions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "install_input_capture"
    ]

    assert len(definitions) == 1


def test_installer_captures_builtin_input(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        request_intercepts,
        "_MULTI_TUI_CAPTURE_INSTALLED",
        False,
    )
    monkeypatch.setattr(
        request_intercepts,
        "_CAPTURED_ORIGINALS",
        {},
    )

    original_input = builtins.input

    monkeypatch.setattr(
        builtins,
        "input",
        lambda _prompt="": "typed instruction",
    )

    captured: list[str] = []

    monkeypatch.setattr(
        request_intercepts,
        "_remember_typed_input",
        captured.append,
    )

    request_intercepts.install_input_capture()

    try:
        assert builtins.input("> ") == "typed instruction"
        assert captured == ["typed instruction"]
    finally:
        builtins.input = original_input
