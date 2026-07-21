from pathlib import Path

from sophyane.platform_kernel import (
    AgentSpec,
    AutoCompactor,
    CodedSandbox,
    EvaluationEngine,
    PromptAdvisor,
    RepositoryKernel,
    SubAgentRuntime,
)


def test_sandbox_rejects_escape(tmp_path: Path):
    sandbox = CodedSandbox(tmp_path)
    manifest = sandbox.prepare()
    assert manifest["policy"]["writes"] == "workspace-only"
    try:
        sandbox.resolve("../escape.txt")
    except ValueError:
        pass
    else:
        raise AssertionError("sandbox allowed path escape")


def test_repository_index_and_checkpoint(tmp_path: Path):
    (tmp_path / "main.py").write_text("def hello():\n    return 'hi'\n", encoding="utf-8")
    kernel = RepositoryKernel(tmp_path)
    index = kernel.index()
    assert index["files"][0]["path"] == "main.py"
    assert "hello" in index["symbols"]["main.py"]
    snapshot = kernel.checkpoint()
    assert snapshot.files["main.py"].startswith("def hello")


def test_eval_and_prompt_advice(tmp_path: Path):
    (tmp_path / "index.html").write_text("<!doctype html><html><body>ok</body></html>", encoding="utf-8")
    result = EvaluationEngine().evaluate(tmp_path)
    assert result.checks["artifact_exists"]
    assert PromptAdvisor.advise("fix it")


def test_subagent_is_provider_neutral(tmp_path: Path):
    runtime = SubAgentRuntime(lambda prompt, system: "verified output", tmp_path)
    result = runtime.run(AgentSpec("tester", "test", ("read", "execute")), "check project")
    assert result.ok
    assert result.name == "tester"


def test_compactor_is_safe_on_empty_tree(tmp_path: Path):
    assert AutoCompactor().compact(tmp_path)["removed_duplicate_snapshots"] == 0
