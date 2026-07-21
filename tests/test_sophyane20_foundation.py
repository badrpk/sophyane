from __future__ import annotations

from pathlib import Path

from sophyane.coi import AgentManifest, COIOrchestrator, TaskContract
from sophyane.engineering_program import ReleaseGate, WORKSTREAMS
from sophyane.platform_kernel import CodedSandbox, EvaluationEngine, PromptAdvisor, RepositoryKernel
from sophyane.provider_state import publish, snapshot


def test_all_six_workstreams_are_declared() -> None:
    assert set(WORKSTREAMS) == {"runtime", "repository", "coi", "sandbox", "evaluation", "prompting"}


def test_provider_state_tracks_rescue() -> None:
    publish(primary="local_gguf", active="gemini", mode="rescue")
    state = snapshot()
    assert state["primary"] == "local_gguf"
    assert state["active"] == "gemini"
    assert state["mode"] == "rescue"


def test_repository_sandbox_eval_and_prompt(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("print('ok')\n", encoding="utf-8")
    index = RepositoryKernel(tmp_path).index()
    assert index["files"]
    assert CodedSandbox(tmp_path / "workspace").prepare()["policy"]["writes"] == "workspace-only"
    assert EvaluationEngine().evaluate(tmp_path).score > 0
    assert PromptAdvisor.advise("Build a tested app; success means it runs.")


def test_coi_dependency_and_permission_flow(tmp_path: Path) -> None:
    coi = COIOrchestrator(tmp_path / "coi")
    coi.register(AgentManifest("coder", "coding", permissions=["read", "write"]), lambda task, context: {"goal": task.goal})
    result = coi.run(TaskContract("build", permissions=["write"]), agent="coder")
    assert result["ok"]
    blocked = coi.run(TaskContract("deploy", dependencies=["missing"]), agent="coder")
    assert blocked["state"] == "blocked"


def test_release_gate_import_mode(tmp_path: Path) -> None:
    for rel in ("README.md", "docs/COI.md", "docs/MCP.md", "docs/PROMPT_GUIDE.md", "docs/EVALUATION.md"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x" * 200, encoding="utf-8")
    (tmp_path / "main.py").write_text("print('ok')\n", encoding="utf-8")
    report = ReleaseGate(tmp_path).run(execute_commands=False)
    assert report.version
    assert report.checks
