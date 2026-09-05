from pathlib import Path

import sophyane.providers.codex_cli as codex_cli
import sophyane.recursive_evolution_controller as rsi


def test_codex_mode_selects_readonly_reviewer(
    tmp_path,
    monkeypatch,
):
    captured = {}

    class FakeCodexProvider:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def generate(self, prompt, system_prompt):
            captured["prompt"] = prompt
            captured["system"] = system_prompt
            return "STATUS: CONTINUE"

    monkeypatch.setattr(
        codex_cli,
        "CodexCliProvider",
        FakeCodexProvider,
    )
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "codex_cli",
    )
    monkeypatch.setenv(
        "SOPHYANE_SESSION_TIMEOUT",
        "240",
    )

    reviewer = rsi.load_mode4_supervisory_reviewer(
        repository=tmp_path,
    )

    assert reviewer("choose one") == "STATUS: CONTINUE"
    assert captured["workspace"] == tmp_path
    assert captured["timeout"] == 240
    assert captured["prompt"] == "choose one"
    assert "read-only" in captured["system"]


def test_supervised_rsi_uses_mode4_loader():
    text = Path(
        "src/sophyane/recursive_evolution_controller.py"
    ).read_text(encoding="utf-8")

    start = text.index(
        "def run_supervised_mode3_nifdu_rsi("
    )

    assert (
        "load_mode4_supervisory_reviewer("
        in text[start:]
    )
