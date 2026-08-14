from __future__ import annotations

from dataclasses import dataclass

import sophyane.v13_cli as cli


def test_default_session_is_race(
    monkeypatch,
):
    monkeypatch.delenv(
        "SOPHYANE_SESSION_MODE",
        raising=False,
    )

    assert (
        cli._execution_session_mode()
        == "race"
    )

    assert (
        cli._should_use_adaptive_race()
        is True
    )


def test_explicit_sli_remains_available(
    monkeypatch,
):
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "sli_graph",
    )

    assert (
        cli._execution_session_mode()
        == "sli_graph"
    )

    assert not (
        cli._should_use_adaptive_race()
    )


def test_explicit_local_remains_available(
    monkeypatch,
):
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "local_llm",
    )

    assert (
        cli._execution_session_mode()
        == "local_llm"
    )


def test_explicit_cloud_remains_available(
    monkeypatch,
):
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "cloud_llm",
    )

    assert (
        cli._execution_session_mode()
        == "cloud_llm"
    )


def test_adaptive_aliases(
    monkeypatch,
):
    for value in (
        "0",
        "adaptive",
        "auto",
        "cooperative",
        "race",
    ):
        monkeypatch.setenv(
            "SOPHYANE_SESSION_MODE",
            value,
        )

        assert (
            cli._execution_session_mode()
            == "race"
        )


@dataclass
class FakeProposal:
    payload: dict


@dataclass
class FakeWinner:
    worker: str
    score: float
    value: FakeProposal


@dataclass
class FakeRace:
    winner: FakeWinner
    errors: dict


@dataclass
class FakeResult:
    race_result: FakeRace

    @property
    def winner(self):
        return (
            self.race_result.winner
        )


def test_execution_bridge_returns_winner(
    monkeypatch,
    tmp_path,
):
    """Default bridge consumes the apply/verify result."""

    import sophyane.race_execution as race_execution

    class FakeExecutionResult:
        ok = True
        winner = "sli"
        attempts = 1
        applied = 1
        verifications = ["pytest: pass"]
        error = None

    calls = []

    def fake_run_race_apply_verify(
        request,
        *,
        workspace,
        config,
        progress=None,
        max_rounds=3,
        race_timeout=180.0,
        **kwargs,
    ):
        calls.append(
            {
                "request": request,
                "workspace": workspace,
                "config": config,
                "progress": progress,
                "max_rounds": max_rounds,
                "race_timeout": race_timeout,
                "kwargs": kwargs,
            }
        )

        return FakeExecutionResult()

    monkeypatch.setattr(
        race_execution,
        "run_race_apply_verify",
        fake_run_race_apply_verify,
    )

    result = (
        cli._run_adaptive_race_request(
            "repair tests",
            workspace=tmp_path,
            config={},
        )
    )

    assert result["ok"] is True
    assert result["winner"] == "sli"
    assert result["attempts"] == 1
    assert result["applied"] == 1
    assert result["verifications"] == [
        "pytest: pass"
    ]
    assert result["error"] is None

    assert len(calls) == 1

    call = calls[0]

    assert call["request"] == "repair tests"
    assert call["workspace"] == tmp_path
    assert call["config"] == {}
    assert call["max_rounds"] == 3
    assert call["race_timeout"] == 180.0
    assert set(call["kwargs"]) == {
        "semantic_judge",
    }

    semantic_judge = call["kwargs"][
        "semantic_judge"
    ]

    assert callable(
        semantic_judge
    )

    assert (
        semantic_judge.__name__
        == "_semantic_completion_judgement"
    )
