from pathlib import Path


WORKFLOW = Path(".github/workflows/tests.yml")


def test_ci_workflow_exists() -> None:
    assert WORKFLOW.is_file()


def test_ci_runs_full_pytest_suite() -> None:
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "python -m pytest -q" in content
    assert "pull_request:" in content
    assert 'branches: ["main"]' in content


def test_ci_covers_supported_python_versions() -> None:
    content = WORKFLOW.read_text(encoding="utf-8")
    for version in ("3.11", "3.12", "3.13"):
        assert f'"{version}"' in content
