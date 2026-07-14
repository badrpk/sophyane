"""Regression tests for v11 autonomous routing."""

from __future__ import annotations

import logging
from pathlib import Path

import sophyane.agent as agent_module
from sophyane.agent import SophyaneAgent


class DummyProvider:
    def generate(self, prompt: str, system_prompt: str) -> str:
        raise AssertionError("Provider must not run for supported workflows")


class DummyMemory:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def record_message(self, role: str, content: str) -> None:
        self.messages.append((role, content))

    def auto_capture(self, _message: str) -> list[str]:
        return []


def test_supported_workflow_runs_before_provider(monkeypatch, tmp_path: Path) -> None:
    request = (
        "Build a minimal inventory REST API using Python, SQLite and automated tests."
    )
    monkeypatch.setattr(agent_module, "supports_autonomous_build", lambda value: value == request)
    monkeypatch.setattr(
        agent_module,
        "run_inventory_workflow",
        lambda value: "=== SOPHYANE AUTONOMOUS BUILD REPORT ===\nFinal result: PASS",
    )

    memory = DummyMemory()
    harness = SophyaneAgent(DummyProvider(), memory, logging.getLogger("test"))
    response = harness.ask(request)

    assert response.text.startswith("=== SOPHYANE AUTONOMOUS BUILD REPORT ===")
    assert memory.messages[0] == ("user", request)
    assert memory.messages[-1][0] == "assistant"
