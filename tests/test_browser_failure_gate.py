from pathlib import Path

from sophyane import adaptive_execution as adaptive
from sophyane.browser_failure_gate import FAILURE_RESULT, install_browser_failure_gate


def test_failed_browser_generation_becomes_terminal(tmp_path: Path, monkeypatch) -> None:
    original = adaptive._one_shot_browser_artifact
    calls = []

    def failed(**kwargs):
        (kwargs["workspace"] / ".sophyane-partial-index.html").write_text(
            "<!doctype html><html><body>rejected</body></html>", encoding="utf-8"
        )
        return None

    monkeypatch.setattr(adaptive, "_one_shot_browser_artifact", failed)
    install_browser_failure_gate()
    gated = adaptive._one_shot_browser_artifact

    result = gated(
        ask=lambda prompt: calls.append(prompt),
        original_request="make snake game",
        workspace=tmp_path,
        progress=lambda message: None,
    )

    assert result == FAILURE_RESULT
    assert "Generic write_file" in result
    monkeypatch.setattr(adaptive, "_one_shot_browser_artifact", original)


def test_successful_browser_generation_passes_through(tmp_path: Path, monkeypatch) -> None:
    original = adaptive._one_shot_browser_artifact

    def succeeded(**kwargs):
        return "Updated and opened the provider-generated browser project."

    monkeypatch.setattr(adaptive, "_one_shot_browser_artifact", succeeded)
    install_browser_failure_gate()

    result = adaptive._one_shot_browser_artifact(
        ask=lambda prompt: None,
        original_request="make snake game",
        workspace=tmp_path,
        progress=lambda message: None,
    )

    assert result.startswith("Updated and opened")
    monkeypatch.setattr(adaptive, "_one_shot_browser_artifact", original)


def test_adaptive_loop_does_not_enter_generic_actions_after_browser_failure(
    tmp_path: Path, monkeypatch
) -> None:
    original = adaptive._one_shot_browser_artifact
    executed = []

    monkeypatch.setattr(adaptive, "_one_shot_browser_artifact", lambda **kwargs: FAILURE_RESULT)
    monkeypatch.setattr(
        "sophyane.execution_runtime.execute_action",
        lambda action, workspace, progress: executed.append(action) or (True, "unexpected"),
    )

    result = adaptive.run_adaptive_loop(
        initial_text='{"action":{"type":"write_file","path":"index.html","content":"bad"}}',
        original_request="make snake game",
        ask=lambda prompt: None,
        workspace=tmp_path,
        progress=lambda message: None,
    )

    assert result == FAILURE_RESULT
    assert executed == []
    assert not (tmp_path / "index.html").exists()
    monkeypatch.setattr(adaptive, "_one_shot_browser_artifact", original)
