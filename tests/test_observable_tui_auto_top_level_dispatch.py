from __future__ import annotations

from dataclasses import dataclass

import sophyane.tui_v2 as tui


@dataclass
class FakeResponse:
    text: str


def test_auto_dispatch_is_separate_from_low_level_provider():
    provider_calls = []
    dispatch_calls = []

    def provider_ask(message):
        provider_calls.append(message)
        return FakeResponse("LOW LEVEL PROVIDER")

    def dispatch(message):
        dispatch_calls.append(message)
        return FakeResponse("AUTO RESULT")

    app = tui.ObservableTUI(
        config={"provider": "gemini"},
        ask=provider_ask,
        handle_internal=lambda *_args, **_kwargs: False,
        dispatch_user_request=dispatch,
    )

    # Structural authority:
    # call_provider must still mean LOW-LEVEL provider generation.
    result = app.call_provider("internal refinement prompt")

    assert result.text == "LOW LEVEL PROVIDER"
    assert provider_calls == ["internal refinement prompt"]
    assert dispatch_calls == []


def test_non_auto_has_no_top_level_dispatch():
    app = tui.ObservableTUI(
        config={"provider": "gemini"},
        ask=lambda message: FakeResponse(message),
        handle_internal=lambda *_args, **_kwargs: False,
    )

    assert app.dispatch_user_request is None


def test_auto_startup_has_separate_guard_and_dispatch(
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "race",
    )

    import sophyane.main as main
    import sophyane.v13_cli as cli

    race_calls = []
    captured = {}

    def forbidden_provider(*args, **kwargs):
        raise AssertionError(
            "Auto constructed ordinary provider"
        )

    monkeypatch.setattr(
        main,
        "create_provider",
        forbidden_provider,
    )

    def fake_race(
        request,
        *,
        workspace,
        config,
        progress=None,
        timeout=180.0,
    ):
        race_calls.append(request)

        return {
            "ok": True,
            "mode": "answer",
            "winner": None,
            "answer": "race answer",
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

    def fake_run(self):
        captured["ask"] = self.ask
        captured["dispatch"] = self.dispatch_user_request
        return 0

    monkeypatch.setattr(
        tui.ObservableTUI,
        "run",
        fake_run,
    )

    assert (
        tui.run_observable_tui(
            config={"provider": "gemini"},
        )
        == 0
    )

    assert callable(captured["ask"])
    assert callable(captured["dispatch"])
    assert captured["ask"] is not captured["dispatch"]

    # Auto's low-level provider seam is deliberately guarded.
    import pytest

    with pytest.raises(RuntimeError):
        captured["ask"](
            "internal provider prompt"
        )

    assert race_calls == []

    response = captured["dispatch"](
        "What is the difference between CSV and JSON?"
    )

    assert response.text == "race answer"

    assert race_calls == [
        "What is the difference between CSV and JSON?"
    ]
