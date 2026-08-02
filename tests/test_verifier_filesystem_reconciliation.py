from pathlib import Path
from typing import Any

from sophyane.strict_interactive_doer import (
    StrictInteractiveCodingDoerRuntime,
)


class FakeReport:
    def __init__(self) -> None:
        self.files: list[Any] = []
        self.commands: list[Any] = []


class FakeExecutor:
    def __init__(self) -> None:
        self.report = FakeReport()


def make_runtime(tmp_path: Path) -> StrictInteractiveCodingDoerRuntime:
    runtime = object.__new__(StrictInteractiveCodingDoerRuntime)
    runtime.workspace = tmp_path
    runtime.executor = FakeExecutor()
    return runtime


def test_verifier_rejects_false_created_file_claims(
    tmp_path: Path,
) -> None:
    runtime = make_runtime(tmp_path)

    verdict = {
        "goal_met": False,
        "confidence": 0.8,
        "missing_requirements": [
            "pyproject.toml and README.md created",
            "src/calculator_service/core.py implemented",
        ],
        "next_instruction": "Continue",
        "final_answer": "",
    }

    reconciled = runtime._reconcile_filesystem_verdict(
        verdict,
        """Create:
- pyproject.toml
- README.md
- src/calculator_service/__init__.py
- src/calculator_service/core.py
- tests/test_calculator.py
""",
        "Build a calculator package",
        [],
    )

    assert reconciled["goal_met"] is False
    assert reconciled["confidence"] == 0
    assert reconciled["verification_mode"] == (
        "filesystem_reconciliation"
    )

    missing = reconciled["missing_requirements"]

    assert "pyproject.toml is missing from the workspace" in missing
    assert "README.md is missing from the workspace" in missing
    assert (
        "src/calculator_service/__init__.py "
        "is missing from the workspace"
    ) in missing
    assert (
        "src/calculator_service/core.py "
        "is missing from the workspace"
    ) in missing
    assert (
        "tests/test_calculator.py is missing from the workspace"
    ) in missing
    assert "No successful filesystem write evidence exists" in missing

    combined = " ".join(missing).lower()

    assert "created" not in combined
    assert "implemented" not in combined


def test_existing_requested_file_is_not_reported_missing(
    tmp_path: Path,
) -> None:
    runtime = make_runtime(tmp_path)

    target = tmp_path / "src/calculator_service/core.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "def add(a, b):\n"
        "    return a + b\n",
        encoding="utf-8",
    )

    verdict = {
        "goal_met": False,
        "missing_requirements": ["Run tests"],
        "next_instruction": "Run tests",
        "final_answer": "",
    }

    original = dict(verdict)

    reconciled = runtime._reconcile_filesystem_verdict(
        verdict,
        "Create src/calculator_service/core.py",
        "",
        [],
    )

    assert reconciled == original


def test_requested_file_extraction_rejects_escape_paths() -> None:
    files = StrictInteractiveCodingDoerRuntime._requested_workspace_files(
        """Create:
pyproject.toml
README.md
src/example/core.py
../escape.py
/absolute/path.py
""",
        "",
        [],
    )

    assert files == [
        "pyproject.toml",
        "README.md",
        "src/example/core.py",
    ]
