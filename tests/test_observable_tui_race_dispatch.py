from __future__ import annotations

from dataclasses import dataclass

import pytest

import sophyane.tui_v2 as tui


@dataclass
class FakeWinner:
    worker: str = "sli"


def test_observable_tui_auto_uses_top_level_race_without_provider(
    monkeypatch,
    tmp_path,
):
    """
    Auto mode must race the original user request at the top-level boundary.

    It must neither construct an ordinary provider nor install the adaptive
    race as the low-level call_provider()/ask callback.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "race",
    )

    import sophyane.main as main
    import sophyane.v13_cli as cli

    calls = []

    def fake_race(
        request,
        *,
        workspace,
        config,
        progress=None,
        timeout=180.0,
    ):
        calls.append(
            {
                "request": request,
                "workspace": workspace,
                "config": config,
            }
        )

        return {
            "ok": True,
            "mode": "answer",
            "winner": FakeWinner(),
            "answer": "CSV is tabular; JSON is hierarchical.",
            "attempts": 1,
            "applied": [],
            "verifications": [],
            "error": None,
        }

    monkeypatch.setattr(
        cli,
        "_run_adaptive_race_request",
        fake_race,
    )

    def forbidden_provider(*args, **kwargs):
        raise AssertionError(
            "Auto mode constructed ordinary provider"
        )

    monkeypatch.setattr(
        main,
        "create_provider",
        forbidden_provider,
    )

    captured = {}

    def fake_run(self):
        captured["ask"] = self.ask
        captured["dispatch"] = self.dispatch_user_request
        return 0

    monkeypatch.setattr(
        tui.ObservableTUI,
        "run",
        fake_run,
    )

    rc = tui.run_observable_tui(
        config={"provider": "gemini"},
    )

    assert rc == 0

    assert callable(captured["ask"])
    assert callable(captured["dispatch"])

    # Low-level provider generation is forbidden in Auto.
    with pytest.raises(
        RuntimeError,
        match="low-level provider callback",
    ):
        captured["ask"](
            "Answer directly. No JSON."
        )

    # The original request races exactly once.
    response = captured["dispatch"](
        "What is the difference between CSV and JSON?"
    )

    assert response.text == (
        "CSV is tabular; JSON is hierarchical."
    )

    assert len(calls) == 1
    assert calls[0]["request"] == (
        "What is the difference between CSV and JSON?"
    )
    assert calls[0]["workspace"] == tmp_path
    assert calls[0]["config"] == {
        "provider": "gemini"
    }


def test_explicit_local_still_constructs_normal_provider(
    monkeypatch,
):
    """
    Explicit Local mode remains provider-authoritative.
    """
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "local_llm",
    )

    import sophyane.agent as agent_module
    import sophyane.main as main

    sentinel_provider = object()
    constructed = []

    class FakeAgent:
        def __init__(
            self,
            provider,
            memory,
            logger,
        ):
            constructed.append(provider)

        def ask(self, message):
            from sophyane.agent import AgentResponse
            return AgentResponse("local")

    monkeypatch.setattr(
        main,
        "create_provider",
        lambda config: sentinel_provider,
    )

    monkeypatch.setattr(
        agent_module,
        "SophyaneAgent",
        FakeAgent,
    )

    monkeypatch.setattr(
        tui.ObservableTUI,
        "run",
        lambda self: 0,
    )

    assert (
        tui.run_observable_tui(
            config={"provider": "gemini"},
        )
        == 0
    )

    assert constructed == [
        sentinel_provider
    ]
