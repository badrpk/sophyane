from __future__ import annotations

from pathlib import Path

import pytest

from sophyane.providers.base import ProviderError


def test_observer_records_structured_success_without_prompt_or_response(
    tmp_path: Path,
):
    from sophyane.intelligence_observer import IntelligenceObserver

    observer = IntelligenceObserver(tmp_path)

    observer.record_attempt(
        provider="nifdu_browser",
        transport="browser",
        model="chatgpt-browser",
        operation="conversation_reply",
        outcome="success",
        latency_seconds=1.25,
        diagnostic="completed",
        prompt="SECRET USER PROMPT",
        response="SECRET MODEL RESPONSE",
    )

    rows = observer.read_recent()

    assert len(rows) == 1

    row = rows[0]

    assert row["provider"] == "nifdu_browser"
    assert row["transport"] == "browser"
    assert row["model"] == "chatgpt-browser"
    assert row["operation"] == "conversation_reply"
    assert row["outcome"] == "success"
    assert row["latency_seconds"] == pytest.approx(1.25)

    serialized = repr(row)

    assert "SECRET USER PROMPT" not in serialized
    assert "SECRET MODEL RESPONSE" not in serialized


def test_observer_records_failure_category_without_sensitive_payload(
    tmp_path: Path,
):
    from sophyane.intelligence_observer import IntelligenceObserver

    observer = IntelligenceObserver(tmp_path)

    observer.record_attempt(
        provider="codex_cli",
        transport="cli",
        model="codex-default",
        operation="conversation_reply",
        outcome="failure",
        failure_category="transport_failure",
        diagnostic="connection failed",
        prompt="DO NOT STORE THIS",
    )

    row = observer.read_recent()[0]

    assert row["outcome"] == "failure"
    assert row["failure_category"] == "transport_failure"
    assert row["provider"] == "codex_cli"

    assert "DO NOT STORE THIS" not in repr(row)


def test_observation_is_not_verified_execution_evidence(
    tmp_path: Path,
):
    from sophyane.intelligence_observer import IntelligenceObserver

    observer = IntelligenceObserver(tmp_path)

    observer.record_attempt(
        provider="local_gguf",
        transport="local",
        model="tiny-test",
        operation="diagnosis",
        outcome="success",
        latency_seconds=0.1,
    )

    row = observer.read_recent()[0]

    assert row.get("verification_state") != "verified"
    assert row.get("accepted") is not True
    assert not row.get("verification_evidence")


def test_observer_bounds_diagnostic_text(
    tmp_path: Path,
):
    from sophyane.intelligence_observer import IntelligenceObserver

    observer = IntelligenceObserver(tmp_path)

    observer.record_attempt(
        provider="api_provider",
        transport="api",
        model="test",
        operation="conversation_reply",
        outcome="failure",
        failure_category="provider_failure",
        diagnostic="X" * 100_000,
    )

    row = observer.read_recent()[0]

    assert len(row.get("diagnostic", "")) <= 1000


def test_observer_assigns_attempt_identity(
    tmp_path: Path,
):
    from sophyane.intelligence_observer import IntelligenceObserver

    observer = IntelligenceObserver(tmp_path)

    observer.record_attempt(
        provider="nifdu_browser",
        transport="browser",
        model="chatgpt-browser",
        operation="conversation_reply",
        outcome="success",
    )

    row = observer.read_recent()[0]

    assert row["event_key"]
    assert row["created_at"]


def test_observer_read_is_bounded(
    tmp_path: Path,
):
    from sophyane.intelligence_observer import IntelligenceObserver

    observer = IntelligenceObserver(tmp_path)

    for index in range(30):
        observer.record_attempt(
            provider="local_gguf",
            transport="local",
            model="tiny",
            operation=f"diagnosis-{index}",
            outcome="success",
        )

    rows = observer.read_recent(limit=5)

    assert len(rows) == 5

def test_default_observer_uses_sanitized_state_path(tmp_path, monkeypatch):
    import sophyane.intelligence_observer as module

    monkeypatch.setattr(module, "STATE_DIR", tmp_path)

    observer = module.default_intelligence_observer()

    assert observer.path == tmp_path / "intelligence-attempts.jsonl"


def test_default_observer_creation_is_fail_open(monkeypatch):
    import sophyane.intelligence_observer as module

    class BrokenObserver:
        def __init__(self, _root):
            raise OSError("storage unavailable")

    monkeypatch.setattr(module, "IntelligenceObserver", BrokenObserver)

    assert module.default_intelligence_observer() is None
