"""Release-level regression tests retained for Sophyane v13."""

from pathlib import Path

import sophyane.autonomous_builder as builder
from sophyane.version import __version__


def test_version_is_13() -> None:
    assert __version__ == "13.0.0"


def test_supported_request_detection() -> None:
    assert builder.supports_request(
        "Build an inventory REST API with SQLite and automated tests"
    )


def test_builder_report_contract(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(builder, "PROJECTS_DIR", tmp_path)
    report = builder.run_inventory_workflow(
        "Build a minimal inventory REST API using Python, SQLite and automated tests. "
        "Do not create index.html. Show acceptance criteria, created files, exact "
        "test command, exit code and test summary."
    )
    project = tmp_path / "inventory_api"
    assert "=== SOPHYANE AUTONOMOUS BUILD REPORT ===" in report
    assert "Test exit code: 0" in report
    assert "Final result: PASS" in report
    assert (project / "benchmark_report.json").is_file()
    assert not any(project.rglob("index.html"))


def test_agent_has_authoritative_early_routing() -> None:
    source = Path(__import__("sophyane.agent").agent.__file__).read_text(
        encoding="utf-8"
    )
    ask_section = source.split("def ask", 1)[1].split("def _execute_route", 1)[0]
    assert "supports_autonomous_build(message)" in ask_section
    assert ask_section.index("supports_autonomous_build(message)") < ask_section.index(
        "selected_route = route(message)"
    )
