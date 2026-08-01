from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "cloud"
        / "telegram_bot.py"
    ).read_text(encoding="utf-8")


def test_telegram_bot_does_not_import_send_telegram() -> None:
    tree = ast.parse(_source())

    imports_send_telegram = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "sophyane.cloud.messaging"
        and any(
            alias.name == "send_telegram"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imports_send_telegram is False


def test_telegram_bot_required_messaging_hooks_remain() -> None:
    source = _source()

    assert "send_email" in source
    assert "send_whatsapp" in source
    assert "load_messaging_env" in source
