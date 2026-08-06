from __future__ import annotations

import json
from pathlib import Path

from sophyane.evolution.validators import (
    _artifact_workspace,
    _python,
)
from sophyane.local_coding_capability import (
    try_coding_request,
)


def test_python_capability_creates_requested_add_and_pytest(
    tmp_path: Path,
) -> None:
    result = try_coding_request(
        (
            "Create calc.py with add(a, b). "
            "Create and run a pytest test proving "
            "add(20, 22) equals 42."
        ),
        workspace=tmp_path,
    )

    assert result is not None
    assert result.ok is True
    assert result.capability == (
        "development.python_create_validate_pytest"
    )
    assert result.files == [
        "calc.py",
        "test_calc.py",
    ]

    source = (
        tmp_path
        / "calc.py"
    ).read_text(
        encoding="utf-8"
    )

    tests = (
        tmp_path
        / "test_calc.py"
    ).read_text(
        encoding="utf-8"
    )

    assert "def add(a:" in source
    assert "return a + b" in source
    assert "assert add(20, 22) == 42" in tests
    assert result.evidence[-1].exit_code == 0


def test_python_capability_creates_requested_multiply(
    tmp_path: Path,
) -> None:
    result = try_coding_request(
        (
            "Create math_probe.py with multiply(a, b), "
            "create a pytest proving multiply(6, 7) "
            "equals 42, and run the test."
        ),
        workspace=tmp_path,
    )

    assert result is not None
    assert result.ok is True

    source = (
        tmp_path
        / "math_probe.py"
    ).read_text(
        encoding="utf-8"
    )

    tests = (
        tmp_path
        / "test_math_probe.py"
    ).read_text(
        encoding="utf-8"
    )

    assert "def multiply(a:" in source
    assert "return a * b" in source
    assert (
        "assert multiply(6, 7) == 42"
        in tests
    )


def test_python_validator_uses_nested_harness_workspace(
    tmp_path: Path,
) -> None:
    artifact = (
        tmp_path
        / ".sophyane-workspace"
    )
    artifact.mkdir()

    (
        artifact
        / "calc.py"
    ).write_text(
        "def add(a, b):\n"
        "    return a + b\n",
        encoding="utf-8",
    )

    (
        artifact
        / "test_calc.py"
    ).write_text(
        "from calc import add\n"
        "\n"
        "def test_add():\n"
        "    assert add(20, 22) == 42\n",
        encoding="utf-8",
    )

    report = {
        "workspace": str(
            artifact
        )
    }

    (
        artifact
        / ".sophyane-harness-report.json"
    ).write_text(
        json.dumps(
            report
        ),
        encoding="utf-8",
    )

    assert (
        _artifact_workspace(
            tmp_path
        )
        == artifact.resolve()
    )

    checks, errors = _python(
        tmp_path
    )

    assert checks == {
        "python_file_exists": True,
        "syntax_valid": True,
        "pytest_passed": True,
    }
    assert errors == []
