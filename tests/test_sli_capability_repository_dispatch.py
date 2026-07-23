from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from sophyane import adaptive_execution
from sophyane.runtime_sli_capability_planner import (
    _format_repository_result,
    _repository_backend,
    classify,
    install_sli_capability_planner,
)


def test_python_project_selects_repository_runtime() -> None:
    plan = classify(
        "Modify the Python source in this repository and run pytest."
    )

    assert plan.project_type == "software_project"
    assert plan.language == "Python"
    assert plan.builder == "REPOSITORY_CODING_RUNTIME"


def test_general_browser_request_does_not_select_repository_runtime() -> None:
    plan = classify(
        "Build a website without specifying a programming language."
    )

    assert plan.builder == "PROVIDER_BOUNDED"


def test_repository_backend_preserves_system_and_prompt() -> None:
    captured: list[str] = []

    def ask(prompt: str):
        captured.append(prompt)
        return SimpleNamespace(text='{"action":{"type":"answer"}}')

    backend = _repository_backend(ask)
    result = backend(
        '{"request":"inspect repository"}',
        "SOPHYANE_ROLE=PLANNER",
    )

    assert result == '{"action":{"type":"answer"}}'
    assert captured == [
        (
            "SOPHYANE_ROLE=PLANNER\n\n"
            '{"request":"inspect repository"}'
        )
    ]


@dataclass
class FakeResult:
    goal_met: bool = True
    stopped_reason: str = "goal_verified"
    final_answer: str = "Patch applied and tests passed."
    steps: tuple[object, ...] = (object(),)
    execution: dict = None

    def __post_init__(self) -> None:
        if self.execution is None:
            self.execution = {
                "files": ["src/demo.py", "tests/test_demo.py"],
                "commands": [
                    {"exit_code": 0, "stdout": "2 passed"},
                    {"exit_code": 1, "stderr": "baseline failure"},
                ],
            }


def test_repository_result_formatter_reports_evidence(
    tmp_path: Path,
) -> None:
    text = _format_repository_result(
        FakeResult(),
        tmp_path,
    )

    assert "Goal verified: True" in text
    assert "Stop reason: goal_verified" in text
    assert "Steps executed: 1" in text
    assert "Repository files indexed/observed: 2" in text
    assert "Commands passed: 1" in text
    assert "Commands failed: 1" in text
    assert "Patch applied and tests passed." in text


def test_installed_planner_dispatches_python_without_html(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = {
        "repository": 0,
        "html": 0,
    }

    def original(**kwargs):
        calls["html"] += 1
        return "HTML runtime"

    monkeypatch.setattr(
        adaptive_execution,
        "run_adaptive_loop",
        original,
    )
    monkeypatch.delattr(
        adaptive_execution,
        "_sli_capability_planner_installed",
        raising=False,
    )

    import sophyane.runtime_sli_capability_planner as planner

    def fake_repository(**kwargs):
        calls["repository"] += 1
        assert kwargs["workspace"] == tmp_path.resolve()
        assert "Python" in kwargs["original_request"]
        return "Repository runtime"

    monkeypatch.setattr(
        planner,
        "_run_repository_coding",
        fake_repository,
    )

    install_sli_capability_planner()

    result = adaptive_execution.run_adaptive_loop(
        initial_text="{}",
        original_request=(
            "Modify the Python source code in this repository."
        ),
        ask=lambda prompt: "{}",
        workspace=tmp_path,
        max_steps=3,
        progress=lambda message: None,
    )

    assert result == "Repository runtime"
    assert calls == {
        "repository": 1,
        "html": 0,
    }


def test_installed_planner_keeps_real_browser_work_on_adaptive_loop(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = {
        "original": 0,
    }

    def original(**kwargs):
        calls["original"] += 1
        return "Browser runtime"

    monkeypatch.setattr(
        adaptive_execution,
        "run_adaptive_loop",
        original,
    )
    monkeypatch.delattr(
        adaptive_execution,
        "_sli_capability_planner_installed",
        raising=False,
    )

    install_sli_capability_planner()

    result = adaptive_execution.run_adaptive_loop(
        initial_text="{}",
        original_request="Build a responsive website for a bakery",
        ask=lambda prompt: "<html></html>",
        workspace=tmp_path,
        max_steps=3,
        progress=lambda message: None,
    )

    assert result == "Browser runtime"
    assert calls["original"] == 1
