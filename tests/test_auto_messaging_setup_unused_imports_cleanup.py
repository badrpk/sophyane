from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "cloud"
        / "auto_messaging_setup.py"
    ).read_text(encoding="utf-8")


def test_auto_messaging_setup_has_no_dead_messaging_imports() -> None:
    tree = ast.parse(_source())

    forbidden: list[str] = []

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "sophyane.cloud.messaging"
        ):
            forbidden.extend(
                alias.name
                for alias in node.names
                if alias.name in {
                    "MESSAGING_ENV",
                    "send_email",
                    "send_whatsapp",
                }
            )

    assert forbidden == []


def test_auto_messaging_setup_keeps_required_messaging_hooks() -> None:
    source = _source()

    assert "_upsert_messaging_env" in source
    assert "send_telegram" in source
    assert "def " in source
