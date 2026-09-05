from __future__ import annotations

from types import SimpleNamespace


def test_race_followup_uses_successful_artifact_without_rerace(monkeypatch):
    import sophyane.tui_v2 as module
    import sophyane.v13_cli as cli
    import sophyane.execution_runtime as runtime

    calls = []
    opened = []

    monkeypatch.setattr(cli, "_execution_session_mode", lambda: "race")
    monkeypatch.setattr(
        cli,
        "_run_adaptive_race_request",
        lambda *args, **kwargs: calls.append(args[0]) or {
            "ok": True,
            "winner": SimpleNamespace(worker="harness:synthetic"),
            "applied": [SimpleNamespace(changed_paths=("index.html",))],
            "attempts": 1,
            "answer": "",
        },
    )
    monkeypatch.setattr(
        runtime,
        "execute_action",
        lambda action, workspace, progress: opened.append(
            (action, workspace)
        ) or (True, "opened prior artifact"),
    )

    class FakeApp:
        def __init__(self, **kwargs):
            self.progress = lambda message: None
            self.dispatch = kwargs["dispatch_user_request"]

        def run(self):
            first = self.dispatch("make a small artifact")
            second = self.dispatch("open it in browser")
            assert first.text.startswith("Adaptive race completed")
            assert second.text == "opened prior artifact"
            return 0

    monkeypatch.setattr(module, "ObservableTUI", FakeApp)
    assert module.run_observable_tui(config={}, verbose=False) == 0
    assert calls == ["make a small artifact"]
    assert len(opened) == 1
    assert opened[0][0] == {"type": "open_browser"}
