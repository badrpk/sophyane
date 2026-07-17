from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

from sophyane.agent import SophyaneAgent
from sophyane.memory import MemoryStore


class CloudFirstFallback:
    metadata = SimpleNamespace(provider_id="fallback")
    primary = "gemini"
    chain = ("gemini", "local_gguf")

    def __init__(self) -> None:
        self.prompt = ""

    def generate(self, prompt: str, system_prompt: str) -> str:
        self.prompt = prompt
        return "Raheem"


def test_cloud_first_fallback_receives_recent_conversation(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "memory.db")
    memory.record_message("user", "Saleem and Raheem are brothers.")
    memory.record_message("assistant", "Okay.")

    provider = CloudFirstFallback()
    agent = SophyaneAgent(
        provider,
        memory,
        logging.getLogger("test-conversation-context"),
    )
    response = agent.ask("What is the name of Saleem's brother?")

    assert response.text == "Raheem"
    assert "Saleem and Raheem are brothers." in provider.prompt
    assert "Recent conversation:" in provider.prompt
