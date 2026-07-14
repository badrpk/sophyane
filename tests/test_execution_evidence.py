from __future__ import annotations

import sys
from pathlib import Path

import pytest

from sophyane.execution_evidence import EvidenceVerifier, WorkspaceExecutor


def test_workspace_write_hash_and_shell_evidence(tmp_path: Path) -> None:
    executor = WorkspaceExecutor(tmp_path, allowed_commands={Path(sys.executable).name})
    file_evidence = executor.write_text("pkg/value.py", "VALUE = 42\n")
    command = executor.run(
        [sys.executable, "-c", "from pkg.value import VALUE; assert VALUE == 42"]
    )
    ok, reasons = EvidenceVerifier().verify(
        executor.report,
        required_files=["value.py"],
        required_commands=[Path(sys.executable).name],
    )
    assert file_evidence.size > 0
    assert len(file_evidence.sha256) == 64
    assert command.exit_code == 0
    assert ok, reasons


def test_path_escape_and_unlisted_command_are_blocked(tmp_path: Path) -> None:
    executor = WorkspaceExecutor(tmp_path)
    with pytest.raises(PermissionError):
        executor.write_text("../escape.txt", "blocked")
    with pytest.raises(PermissionError):
        executor.run(["not-allowed-command"])


def test_failed_command_prevents_verified_status(tmp_path: Path) -> None:
    executable = Path(sys.executable).name
    executor = WorkspaceExecutor(tmp_path, allowed_commands={executable})
    executor.write_text("artifact.txt", "created")
    executor.run([sys.executable, "-c", "raise SystemExit(7)"])
    ok, reasons = EvidenceVerifier().verify(executor.report)
    assert not ok
    assert not executor.report.verified
    assert any("exit=7" in reason for reason in reasons)


def test_text_claim_without_evidence_cannot_pass(tmp_path: Path) -> None:
    executor = WorkspaceExecutor(tmp_path)
    ok, reasons = EvidenceVerifier().verify(executor.report)
    assert not ok
    assert "no filesystem evidence" in reasons
    assert "no shell evidence" in reasons
