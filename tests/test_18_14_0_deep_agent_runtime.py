from pathlib import Path


def test_prepare_workspace_creates_sandbox(monkeypatch, tmp_path: Path):
    from sophyane import deep_agent_runtime as runtime

    monkeypatch.setattr(runtime, "ROOT", tmp_path / ".sophyane")
    workspace = tmp_path / "task"
    prepared = runtime.prepare_workspace(workspace, request="build demo")

    assert prepared == workspace.resolve()
    assert (prepared / "input").is_dir()
    assert (prepared / "output").is_dir()
    assert (prepared / "tmp").is_dir()
    assert (prepared / "logs").is_dir()
    assert (prepared / ".sophyane" / "sandbox.json").is_file()


def test_runtime_root_reports_capabilities(monkeypatch, tmp_path: Path):
    from sophyane import deep_agent_runtime as runtime

    monkeypatch.setattr(runtime, "ROOT", tmp_path / ".sophyane")
    report = runtime.ensure_runtime_root()
    assert report["writable"] is True
    assert "python" in report["capabilities"]
    assert Path(report["directories"]["workspaces"]).is_dir()
