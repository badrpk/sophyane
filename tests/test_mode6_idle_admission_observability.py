
import ast
import copy
from pathlib import Path
from unittest.mock import patch

import sophyane.adaptive_execution as ae
import sophyane.human_conversation as hc
import sophyane.discovery_provider_reasoner as dpr
import sophyane.rsi.supervisor as supervisor


def test_provider_is_told_idle_does_not_forbid_new_execution(monkeypatch):
    captured = {}

    class Reasoner:
        def __call__(self, operation, payload):
            captured.update(payload)
            return '{"reply":"pending","semantic_disposition":"actionable_mission"}'

    monkeypatch.setattr(dpr, "SessionProviderReasoner", Reasoner)
    hc._default_responder(
        "Run tests in the specified workspace. Do not modify any files.",
        {"trusted_context": {
            "runtime": {"repository_execution": {"job_active": False}}
        }},
    )
    assert captured["trusted_context"]["runtime"]["repository_execution"]["job_active"] is False
    instructions = " ".join(captured["instructions"])
    assert "False means no job is currently running" in instructions
    assert "does not establish that starting a new job is forbidden" in instructions
