"""Failure-injection tests for the bounded multi-repository daemon cycle."""

import json
import sqlite3

from sophyane.rsi.curriculum import CurriculumTask, TaskSource
from sophyane.rsi.curriculum_proposals import ProposalResult
from sophyane.rsi_terminal import run_multi_repo_cycle

from test_continuous_multi_repo_runtime import _runtime


def events(runtime):
    path = runtime.scheduler.store.events_path
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_broken_ast_parser_pauses_at_proposal_boundary(tmp_path):
    runtime, calls = _runtime(tmp_path)

    class BrokenParser:
        def propose(self, _context):
            raise SyntaxError("broken AST parser")

    runtime.task_source = BrokenParser()
    result = run_multi_repo_cycle(runtime, "proposal", max_files=1)
    assert result["status"] == "paused"
    assert "ast" in result["reason"].lower()
    assert runtime.scheduler.status()["paused"] is True
    assert calls == []
    assert any("ast" in str(item).lower() for item in events(runtime))


def test_locked_state_pauses_at_scheduler_boundary(tmp_path):
    runtime, calls = _runtime(tmp_path)

    def locked():
        raise sqlite3.OperationalError("database is locked")

    runtime.scheduler.store.load = locked
    result = run_multi_repo_cycle(runtime, "inventory", max_files=1)
    assert result["status"] == "paused"
    assert "sqlite" in result["reason"].lower() or "locked" in result["reason"].lower()
    assert calls == []


def test_corrupt_git_commit_pauses_at_inventory_boundary(tmp_path):
    runtime, calls = _runtime(tmp_path)

    def corrupt():
        raise ValueError("corrupt git commit hash")

    runtime.repository_inventory.refresh = corrupt
    result = run_multi_repo_cycle(runtime, "inventory", max_files=1)
    assert result["status"] == "paused"
    assert "git" in result["reason"].lower() or "commit" in result["reason"].lower()
    assert calls == []


def test_external_symlink_pauses_at_proposal_boundary(tmp_path):
    runtime, calls = _runtime(tmp_path)
    record = runtime.repository_inventory.records[0]
    repo = tmp_path / "repos" / "alpha"
    outside = tmp_path / "outside-secret.py"
    outside.write_text("secret = True\n")
    (repo / "src" / "escape.py").symlink_to(outside)

    class EscapingSource:
        def propose(self, context):
            task = CurriculumTask(
                "escape", "seed", "escape", ("src/escape.py",), ("pytest",),
                TaskSource.CURRICULUM, repository_id=record.repo_id,
                base_commit=record.commit,
            )
            return ProposalResult(True, task, generator="chaos", review_outcome="approved")

    runtime.task_source = EscapingSource()
    result = run_multi_repo_cycle(runtime, "proposal", max_files=1)
    assert result["status"] == "paused"
    assert "symlink" in result["reason"].lower() or "path" in result["reason"].lower()
    assert calls == []
    assert outside.read_text() == "secret = True\n"
