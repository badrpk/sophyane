from __future__ import annotations

import logging
from pathlib import Path

from sophyane.agent import SophyaneAgent
from sophyane.memory import MemoryStore


class ProviderMustNotRun:
    def generate(self, prompt: str, system_prompt: str) -> str:
        raise AssertionError("deterministic memory recall must not call a model")


def test_last_question_is_recalled_across_store_instances(tmp_path: Path) -> None:
    database = tmp_path / "memory.db"
    first_session = MemoryStore(database)
    first_session.record_message("user", "2+2")
    first_session.record_message("assistant", "4")

    second_session = MemoryStore(database)
    agent = SophyaneAgent(
        ProviderMustNotRun(),
        second_session,
        logging.getLogger("test-memory-recall"),
    )

    response = agent.ask("What was my last question to you?")

    assert response.text == 'Your last question was: "2+2"'
    assert second_session.latest_message("user")["content"] == (
        "What was my last question to you?"
    )
