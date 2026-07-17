from __future__ import annotations

import sys
from types import SimpleNamespace

import sophyane.v13_cli as cli


def test_one_shot_prompt_uses_module_provider_factory(monkeypatch, capsys) -> None:
    provider = object()

    class FakeAgent:
        def __init__(self, selected_provider, memory, logger) -> None:
            assert selected_provider is provider

        def ask(self, prompt: str):
            assert prompt == "Reply with exactly: SPEED_OK"
            return SimpleNamespace(text="SPEED_OK")

    monkeypatch.setattr(sys, "argv", ["sophyane", "Reply with exactly: SPEED_OK"])
    monkeypatch.setattr(cli, "load_runtime_config", lambda: {"provider": "gemini"})
    monkeypatch.setattr(cli, "create_provider", lambda config: provider)
    monkeypatch.setattr(cli, "MemoryStore", lambda: object())
    monkeypatch.setattr(cli, "SophyaneAgent", FakeAgent)

    assert cli.main() == 0
    assert "SPEED_OK" in capsys.readouterr().out
