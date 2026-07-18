from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import sophyane.providers.gemini as gemini_module
from sophyane.agent import SophyaneAgent
from sophyane.coding_runtime import MechanicalVerifier
from sophyane.memory import MemoryStore
from sophyane.providers.base import ProviderMetadata
from sophyane.providers.fallback import FallbackProvider
from sophyane.providers.gemini import GeminiProvider


class RecordingGemini:
    metadata = ProviderMetadata(
        provider_id="gemini",
        display_name="Gemini",
        default_model="gemini-2.5-flash",
        environment_variable="GEMINI_API_KEY",
    )

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.model = "gemini-2.5-flash"
        self.timeout = 10
        self.temperature = 0.0
        self.max_tokens = 100

    def generate(self, prompt: str, system_prompt: str) -> str:
        self.prompts.append(prompt)
        return "The server is Aurora."


def test_cloud_fallback_keeps_recent_conversation(tmp_path: Path) -> None:
    gemini = RecordingGemini()
    provider = FallbackProvider([("gemini", gemini)], primary="gemini")
    provider.last_provider = "gemini"
    agent = SophyaneAgent(
        provider,
        MemoryStore(tmp_path / "memory.db"),
        logging.getLogger("v18-memory"),
    )

    agent.ask("Call my server Aurora.")
    agent.ask("What did I call my server?")

    prompt = gemini.prompts[-1]
    assert "Recent conversation:" in prompt
    assert "Call my server Aurora." in prompt
    assert "The server is Aurora." in prompt


def test_gemini_records_provider_usage(monkeypatch) -> None:
    monkeypatch.setattr(
        gemini_module,
        "post_json",
        lambda *args, **kwargs: {
            "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
            "usageMetadata": {
                "promptTokenCount": 11,
                "candidatesTokenCount": 7,
                "thoughtsTokenCount": 3,
                "totalTokenCount": 21,
            },
        },
    )
    provider = GeminiProvider("key", "gemini-2.5-flash")
    assert provider.generate("hello", "system") == "ok"
    assert provider.get_token_usage() == {
        "input_tokens": 11,
        "output_tokens": 7,
        "thinking_tokens": 3,
        "total_tokens": 21,
        "model_calls": 1,
    }


def test_mechanical_verifier_accepts_common_model_aliases(tmp_path: Path) -> None:
    observation = {
        "argv": [sys.executable, "test_app.py"],
        "exit_code": 0,
        "stdout": "SMOKE_PASS\n",
        "stderr": "",
        "timed_out": False,
    }
    result = MechanicalVerifier(tmp_path).verify(
        [
            {
                "type": "command_exit_zero",
                "command": [sys.executable, "test_app.py"],
            },
            {
                "type": "stdout_contains",
                "expected_string": "SMOKE_PASS",
            },
        ],
        command_observations=[observation],
    )
    assert result["passed"], json.dumps(result, indent=2)


def test_empty_stdout_check_never_passes(tmp_path: Path) -> None:
    result = MechanicalVerifier(tmp_path).verify(
        [{"type": "stdout_contains", "expected_string": ""}],
        command_observations=[{"stdout": "anything"}],
    )
    assert not result["passed"]
