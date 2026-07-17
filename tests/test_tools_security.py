from __future__ import annotations

from pathlib import Path

import sophyane.tools as local_tools


def test_file_tools_are_confined_to_workspace(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "allowed.txt").write_text("allowed", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    monkeypatch.setattr(local_tools, "WORKSPACE_DIR", workspace)

    allowed = local_tools.read_text_file("allowed.txt")
    escaped = local_tools.read_text_file("../outside.txt")
    absolute = local_tools.read_text_file(str(outside))

    assert allowed.successful is True
    assert "allowed" in allowed.output
    assert escaped.successful is False
    assert "outside the Sophyane workspace" in escaped.output
    assert absolute.successful is False


def test_symlink_cannot_escape_workspace(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = workspace / "escape.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        return
    monkeypatch.setattr(local_tools, "WORKSPACE_DIR", workspace)

    result = local_tools.read_text_file("escape.txt")

    assert result.successful is False
    assert "outside the Sophyane workspace" in result.output


def test_shell_rejects_general_purpose_code_execution() -> None:
    for command in (
        "python3 -c 'print(1)'",
        "pip install example",
        "git status",
        "cat /etc/passwd",
        "env",
    ):
        result = local_tools.safe_shell(command, require_confirmation=False)
        assert result.successful is False, command
