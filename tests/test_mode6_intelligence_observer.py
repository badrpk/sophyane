from __future__ import annotations

import pytest

from sophyane.providers.base import ProviderError
from sophyane.providers.human_conversation import HumanConversationProvider


class RecordingObserver:
    def __init__(self):
        self.rows = []

    def record_attempt(self, **row):
        self.rows.append(dict(row))


class Candidate:
    def __init__(self, name):
        self.provider_id = name
        self.model = name + "-model"


def test_read_only_observes_failure_then_success(monkeypatch):
    observer = RecordingObserver()
    provider = HumanConversationProvider()
    provider.observer = observer

    def create(name):
        if name == "codex_cli":
            raise ProviderError("connection unavailable")
        return Candidate(name)

    monkeypatch.setattr(provider, "_create", create)

    result = provider.run_request(
        lambda candidate: "answered-" + candidate.provider_id
    )

    assert result == "answered-nifdu_browser"
    assert [row["provider"] for row in observer.rows] == [
        "codex_cli",
        "nifdu_browser",
    ]
    assert [row["outcome"] for row in observer.rows] == [
        "failure",
        "success",
    ]


def test_read_only_terminal_failure_is_observed_without_switch(monkeypatch):
    observer = RecordingObserver()
    provider = HumanConversationProvider()
    provider.observer = observer
    created = []

    def create(name):
        created.append(name)
        return Candidate(name)

    monkeypatch.setattr(provider, "_create", create)

    def request(_candidate):
        raise PermissionError("authority violation")

    with pytest.raises(PermissionError, match="authority violation"):
        provider.run_request(request)

    assert created == ["codex_cli"]
    assert len(observer.rows) == 1
    assert observer.rows[0]["provider"] == "codex_cli"
    assert observer.rows[0]["outcome"] == "failure"


def test_broken_observer_never_changes_read_only_failover(monkeypatch):
    class BrokenObserver:
        def record_attempt(self, **_row):
            raise RuntimeError("observer unavailable")

    provider = HumanConversationProvider()
    provider.observer = BrokenObserver()

    def create(name):
        if name == "codex_cli":
            raise ProviderError("connection unavailable")
        return Candidate(name)

    monkeypatch.setattr(provider, "_create", create)

    assert provider.run_request(
        lambda candidate: candidate.provider_id
    ) == "nifdu_browser"
