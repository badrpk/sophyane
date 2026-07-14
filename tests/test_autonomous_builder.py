"""Tests for Sophyane's stateful autonomous software builder."""

from __future__ import annotations

import json
from pathlib import Path

import sophyane.autonomous_builder as builder


def test_inventory_request_detection() -> None:
    assert builder.supports_request(
        "Build a minimal inventory REST API using Python, SQLite and automated tests."
    )
    assert not builder.supports_request("Make a news website")


def test_inventory_graph_creates_tests_and_verifies(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(builder, "PROJECTS_DIR", tmp_path)

    report = builder.run_inventory_workflow(
        "Build a minimal inventory REST API using Python, SQLite and automated tests. "
        "Do not create index.html. Show acceptance criteria, created files, exact "
        "test command, exit code and test summary."
    )

    project = tmp_path / "inventory_api"
    assert (project / "app.py").is_file()
    assert (project / "test_app.py").is_file()
    assert (project / "README.md").is_file()
    assert not (project / "index.html").exists()

    evidence = json.loads(
        (project / "benchmark_report.json").read_text(encoding="utf-8")
    )
    assert evidence["test_exit_code"] == 0
    assert evidence["verified"] is True
    assert all(evidence["checks"].values())
    assert "Final result: PASS" in report
    assert "Test exit code: 0" in report
