from __future__ import annotations

import sophyane.tui_v2 as tui


def test_auto_race_receives_observable_tui_progress(
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "race",
    )

    import sophyane.v13_cli as cli

    captured = {}

    def fake_race(
        request,
        *,
        workspace,
        config,
        progress=None,
        timeout=180.0,
    ):
        captured["request"] = request
        captured["progress"] = progress

        assert callable(progress)
        progress("RACE PROGRESS SENTINEL")

        return {
            "ok": True,
            "mode": "answer",
            "winner": None,
            "answer": "done",
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

    observed = []

    original_progress = tui.ObservableTUI.progress

    def capture_progress(self, text):
        observed.append(text)

    monkeypatch.setattr(
        tui.ObservableTUI,
        "progress",
        capture_progress,
    )

    def fake_run(self):
        response = self.dispatch_user_request(
            "build something"
        )
        captured["response"] = response.text
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
    assert captured["request"] == "build something"
    assert callable(captured["progress"])
    assert observed[0] == (
        "RACE PROGRESS SENTINEL"
    )

    assert len(observed) == 2

    assert observed[1].startswith(
        "SLI recorded adaptive race execution "
    )

    assert "reward=" in observed[1]
    assert captured["response"] == "done"
