from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import sophyane.sli_learner as learner
import sophyane.sli_schema as schema
import sophyane.tui_v2 as tui
import sophyane.v13_cli as cli


def test_auto_race_success_learns_once(
    monkeypatch,
    tmp_path: Path,
):
    race_calls = []
    learn_calls = []
    progress_calls = []

    class FakeApp:
        def __init__(
            self,
            *,
            config,
            ask,
            handle_internal,
            dispatch_user_request,
        ):
            del config, ask, handle_internal

            self.dispatch = dispatch_user_request
            self.progress = progress_calls.append

        def run(self):
            response = self.dispatch(
                "Create proof.txt containing exactly: proof"
            )

            assert (
                "Adaptive race completed successfully"
                in response.text
            )

            return 0

    def fake_race(
        message,
        *,
        workspace,
        config,
        progress,
    ):
        del config

        race_calls.append(message)

        (workspace / "proof.txt").write_text(
            "proof",
            encoding="utf-8",
        )

        progress("synthetic race succeeded")

        return {
            "ok": True,
            "answer": "",
            "winner": SimpleNamespace(worker="sli"),
            "attempts": 1,
            "applied": [
                {
                    "type": "write_file",
                    "path": "proof.txt",
                }
            ],
        }

    def fake_learn_execution(**kwargs):
        learn_calls.append(kwargs)

        return {
            "trace_id": kwargs["trace_id"],
            "quality_reward": 1.0,
        }

    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(
        cli,
        "_execution_session_mode",
        lambda: "race",
    )

    monkeypatch.setattr(
        cli,
        "_run_adaptive_race_request",
        fake_race,
    )

    monkeypatch.setattr(
        schema,
        "ensure_current_schema",
        lambda: None,
    )

    monkeypatch.setattr(
        learner,
        "learn_execution",
        fake_learn_execution,
    )

    monkeypatch.setattr(
        tui,
        "ObservableTUI",
        FakeApp,
    )

    result = tui.run_observable_tui(
        config={},
        verbose=False,
    )

    assert result == 0
    assert len(race_calls) == 1
    assert len(learn_calls) == 1

    call = learn_calls[0]

    assert call["request"] == (
        "Create proof.txt containing exactly: proof"
    )
    assert call["status"] == "succeeded"
    assert call["trace_id"].startswith(
        "auto-race-"
    )

    # runtime_orchestration_patch._snapshot() contract:
    #
    #     dict[relative_path, sha256_hex]
    #
    # It is intentionally not the bounded {files, bytes, sample}
    # structure used by some SLI graph diagnostics.
    import hashlib

    before = call["workspace_before"]
    after = call["workspace_after"]

    assert isinstance(before, dict)
    assert isinstance(after, dict)

    assert "proof.txt" not in before
    assert "proof.txt" in after

    assert after["proof.txt"] == hashlib.sha256(
        b"proof"
    ).hexdigest()

    assert (
        tmp_path / "proof.txt"
    ).read_bytes() == b"proof"


def test_auto_race_failure_does_not_learn(
    monkeypatch,
    tmp_path: Path,
):
    learn_calls = []

    class FakeApp:
        def __init__(
            self,
            *,
            config,
            ask,
            handle_internal,
            dispatch_user_request,
        ):
            del config, ask, handle_internal

            self.dispatch = dispatch_user_request
            self.progress = lambda _message: None

        def run(self):
            response = self.dispatch("synthetic failure")

            assert "failed safely" in response.text

            return 0

    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(
        cli,
        "_execution_session_mode",
        lambda: "race",
    )

    monkeypatch.setattr(
        cli,
        "_run_adaptive_race_request",
        lambda *args, **kwargs: {
            "ok": False,
            "error": "synthetic failure",
        },
    )

    monkeypatch.setattr(
        learner,
        "learn_execution",
        lambda **kwargs: learn_calls.append(kwargs),
    )

    monkeypatch.setattr(
        tui,
        "ObservableTUI",
        FakeApp,
    )

    assert tui.run_observable_tui(
        config={},
        verbose=False,
    ) == 0

    assert learn_calls == []


def test_auto_race_learning_failure_preserves_success(
    monkeypatch,
    tmp_path: Path,
):
    class FakeApp:
        def __init__(
            self,
            *,
            config,
            ask,
            handle_internal,
            dispatch_user_request,
        ):
            del config, ask, handle_internal

            self.dispatch = dispatch_user_request
            self.progress_messages = []
            self.progress = self.progress_messages.append

        def run(self):
            response = self.dispatch(
                "Create proof.txt containing exactly: proof"
            )

            assert (
                "Adaptive race completed successfully"
                in response.text
            )

            assert any(
                "recording skipped safely"
                in item
                for item in self.progress_messages
            )

            return 0

    def fake_race(
        message,
        *,
        workspace,
        config,
        progress,
    ):
        del message, config, progress

        (workspace / "proof.txt").write_text(
            "proof",
            encoding="utf-8",
        )

        return {
            "ok": True,
            "winner": SimpleNamespace(worker="sli"),
            "attempts": 1,
            "applied": [{}],
        }

    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(
        cli,
        "_execution_session_mode",
        lambda: "race",
    )

    monkeypatch.setattr(
        cli,
        "_run_adaptive_race_request",
        fake_race,
    )

    monkeypatch.setattr(
        schema,
        "ensure_current_schema",
        lambda: None,
    )

    def fail_learning(**kwargs):
        del kwargs
        raise RuntimeError("synthetic learner failure")

    monkeypatch.setattr(
        learner,
        "learn_execution",
        fail_learning,
    )

    monkeypatch.setattr(
        tui,
        "ObservableTUI",
        FakeApp,
    )

    assert tui.run_observable_tui(
        config={},
        verbose=False,
    ) == 0

    assert (
        tmp_path / "proof.txt"
    ).read_bytes() == b"proof"
