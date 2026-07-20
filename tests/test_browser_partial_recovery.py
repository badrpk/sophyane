from pathlib import Path
from types import SimpleNamespace

from sophyane import adaptive_execution as adaptive
from sophyane.browser_partial_recovery import PARTIAL_NAME, install_browser_partial_recovery


def test_recovery_uses_more_than_two_continuations_and_removes_partial(tmp_path, monkeypatch):
    original = adaptive._one_shot_browser_artifact
    responses = iter([
        '<!doctype html><html><body><script>const x="',
        'hello";\n',
        'function f(){return 1;}\n',
        '</script></body></html>',
    ])

    monkeypatch.setattr(adaptive, "_one_shot_browser_artifact", original)
    install_browser_partial_recovery()
    recovered = adaptive._one_shot_browser_artifact
    monkeypatch.setattr(
        "sophyane.execution_runtime.execute_action",
        lambda action, workspace, progress: (True, "opened"),
    )

    result = recovered(
        ask=lambda prompt: SimpleNamespace(text=next(responses)),
        original_request="make a browser game",
        workspace=tmp_path,
        progress=lambda message: None,
    )

    assert result is not None
    assert "3 continuation attempt(s)" in result
    assert (tmp_path / "index.html").is_file()
    assert not (tmp_path / PARTIAL_NAME).exists()


def test_failed_recovery_preserves_best_partial(tmp_path, monkeypatch):
    original = adaptive._one_shot_browser_artifact
    monkeypatch.setattr(adaptive, "_one_shot_browser_artifact", original)
    install_browser_partial_recovery()
    recovered = adaptive._one_shot_browser_artifact

    responses = iter([
        '<!doctype html><html><body><script>const message="',
        "",
        "",
    ])
    result = recovered(
        ask=lambda prompt: SimpleNamespace(text=next(responses)),
        original_request="make a browser game",
        workspace=tmp_path,
        progress=lambda message: None,
    )

    assert result is None
    saved = tmp_path / PARTIAL_NAME
    assert saved.is_file()
    assert "const message" in saved.read_text(encoding="utf-8")


def test_finish_reason_is_reported(tmp_path, monkeypatch):
    original = adaptive._one_shot_browser_artifact
    monkeypatch.setattr(adaptive, "_one_shot_browser_artifact", original)
    install_browser_partial_recovery()
    recovered = adaptive._one_shot_browser_artifact
    messages = []

    recovered(
        ask=lambda prompt: SimpleNamespace(
            text='<!doctype html><html><body><script>', finish_reason="MAX_TOKENS"
        ),
        original_request="make a browser game",
        workspace=tmp_path,
        progress=messages.append,
    )

    assert any("MAX_TOKENS" in message for message in messages)
