from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import sophyane.adaptive_execution as adaptive
import sophyane.browser_partial_recovery as recovery
import sophyane.execution_runtime as execution_runtime
import sophyane.runtime_sli_brain as brain


def test_browser_program_gets_web_profile() -> None:
    decision = brain.decide(
        "make a program to add numbers in browser",
        has_project=False,
    )

    assert decision.route == "execution"
    assert decision.profile == "WEB_STANDARD"
    assert "responsive" in decision.refined_request.lower()
    assert "browser project" in decision.refined_request.lower()


def test_explicit_browser_program_skips_semantic_provider() -> None:
    progress: list[str] = []

    class FakeBrain:
        def progress(self, message: str) -> None:
            progress.append(message)

        def call_provider(self, prompt: str) -> object:
            raise AssertionError(
                "semantic provider must not be called for explicit "
                "browser-program intent"
            )

    result = brain._confirm(
        FakeBrain(),
        "make a program to add numbers in browser",
        has_project=False,
        tui_v2=SimpleNamespace(),
    )

    assert result is not None
    route, refined = result

    assert route == "execution"
    assert "add numbers" in refined
    assert any(
        "resolved deterministically" in message
        for message in progress
    )


def test_zero_html_retries_then_builds_addition_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    responses = [
        SimpleNamespace(
            text="I will plan the application first.",
        ),
        SimpleNamespace(
            text='{"objective":"create calculator"}',
        ),
    ]
    prompts: list[str] = []
    progress: list[str] = []

    def ask(prompt: str) -> object:
        prompts.append(prompt)
        return responses.pop(0)

    monkeypatch.setenv(
        "SOPHYANE_PROVIDER_DIAGNOSTIC_DIR",
        str(tmp_path / "state-provider-responses"),
    )

    monkeypatch.setattr(
        execution_runtime,
        "execute_action",
        lambda action, workspace, callback: (
            True,
            "browser-opened",
        ),
    )

    original = adaptive._one_shot_browser_artifact

    try:
        recovery.install_browser_partial_recovery()
        generated = adaptive._one_shot_browser_artifact

        result = generated(
            ask=ask,
            original_request=(
                "make a program to add numbers in browser"
            ),
            workspace=tmp_path / "workspace",
            progress=progress.append,
        )
    finally:
        adaptive._one_shot_browser_artifact = original

    workspace = tmp_path / "workspace"
    index = workspace / "index.html"

    assert result is not None
    assert workspace.is_dir()
    assert index.is_file()

    html = index.read_text(encoding="utf-8")

    assert "<!doctype html>" in html.lower()
    assert html.lower().endswith("</html>")
    assert "Add Numbers" in html
    assert 'id="first"' in html
    assert 'id="second"' in html
    assert "a+b" in html

    assert len(prompts) == 2
    assert "previous response contained no HTML" in prompts[1]

    assert any(
        "strict fresh HTML retry" in message
        for message in progress
    )
    assert any(
        "deterministic addition-calculator fallback" in message
        for message in progress
    )


def test_provider_evidence_path_is_state_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "repository"
    state = tmp_path / "state"

    workspace.mkdir()

    monkeypatch.setenv(
        "SOPHYANE_PROVIDER_DIAGNOSTIC_DIR",
        str(state),
    )

    saved = recovery._save_raw(
        workspace,
        "run",
        1,
        "provider output",
    )

    assert saved.is_file()
    assert state.resolve() in saved.parents
    assert workspace.resolve() not in saved.parents
    assert not list(
        workspace.glob(".sophyane-provider-response-*")
    )
