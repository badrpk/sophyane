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

    # This test verifies bounded HTML continuation recovery, not Chromium,
    # screenshot capture, or visual-model quality. Supply deterministic
    # evidence so the mandatory production visual gate remains intact.
    shot = tmp_path / "quality.png"
    shot.write_bytes(b"x" * 2000)

    rendered = SimpleNamespace(
        available=True,
        ok=True,
        images=0,
        broken_images=0,
        console_errors=0,
        log_errors=0,
        horizontal_overflow=False,
    )

    monkeypatch.setattr(
        "sophyane.browser_partial_recovery._capture_quality_evidence",
        lambda workspace, target, progress: (rendered, shot),
    )

    monkeypatch.setattr(
        "sophyane.browser_partial_recovery._nifdu_visual_judge",
        lambda **kwargs: {
            "accepted": True,
            "score": 95,
            "critical_issues": 0,
            "unmet_requirements": 0,
            "repair_code": "NONE",
            "summary": "Accepted by test visual judge.",
            "problems": [],
            "repair_instruction": "No judge-requested repair.",
        },
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
