from __future__ import annotations

import os

import json
from pathlib import Path

from sophyane.unified_execution_kernel import (
    capability_catalog,
    execute_request,
)


def test_capability_catalog_contains_coding() -> None:
    names = {
        item["capability"]
        for item in capability_catalog()
    }
    assert "development.local_coding" in names


def test_create_compile_run_cpp(tmp_path: Path) -> None:
    result = execute_request(
        'create hello.cpp compile and run it printing "Hello Test"',
        workspace=tmp_path,
    )

    assert result is not None
    assert result.ok
    assert (tmp_path / "hello.cpp").is_file()
    executable = (
        "hello.exe"
        if os.name == "nt"
        else "hello"
    )
    assert (tmp_path / executable).is_file()

    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["evidence"][-1]["stdout"].strip() == "Hello Test"


def test_create_validate_run_python(tmp_path: Path) -> None:
    result = execute_request(
        'create hello.py and run it printing "Python Test"',
        workspace=tmp_path,
    )

    assert result is not None
    assert result.ok
    assert (tmp_path / "hello.py").is_file()

    payload = json.loads(result.output)
    assert payload["evidence"][-1]["stdout"].strip() == "Python Test"


def test_explanation_is_not_executed(tmp_path: Path) -> None:
    result = execute_request(
        "what is hello.cpp",
        workspace=tmp_path,
    )

    assert result is None
    assert not (tmp_path / "hello.cpp").exists()
