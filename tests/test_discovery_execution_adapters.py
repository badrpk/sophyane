from __future__ import annotations

from pathlib import Path

from sophyane.discovery_contract import (
    ExperimentPlan,
)
from sophyane.discovery_execution_adapters import (
    execute_python_experiment,
)


def plan(
    source,
    *,
    experiment_type="simulation",
):
    return ExperimentPlan(
        experiment_id="experiment-1",
        candidate_id="candidate-1",
        experiment_type=experiment_type,
        procedure=(
            "PYTHON_SOURCE:\n"
            + source,
        ),
        success_criteria=(
            "candidate beats baseline",
        ),
        safe_for_autonomous_execution=True,
    )


def test_safe_simulation_executes_and_measures(
    tmp_path: Path,
):
    result = execute_python_experiment(
        plan(
            """
import json

baseline = sum([1, 1, 1])
candidate = sum([2, 2, 2])

print(json.dumps({
    "baseline_score": baseline,
    "candidate_score": candidate
}))
"""
        ),
        str(tmp_path),
    )

    assert result.executed is True
    assert result.ok is True
    assert result.measurements["baseline_score"] == 3
    assert result.measurements["candidate_score"] == 6
    assert result.evidence["deterministic_verified"] is True


def test_failed_comparison_is_not_verified(
    tmp_path: Path,
):
    result = execute_python_experiment(
        plan(
            """
import json

print(json.dumps({
    "baseline_score": 10,
    "candidate_score": 9
}))
"""
        ),
        str(tmp_path),
    )

    assert result.executed is True
    assert result.ok is True
    assert result.evidence["deterministic_verified"] is False


def test_file_access_is_blocked(
    tmp_path: Path,
):
    result = execute_python_experiment(
        plan(
            """
open("bad.txt", "w").write("bad")
print("{}")
"""
        ),
        str(tmp_path),
    )

    assert result.executed is False
    assert "CALL_BLOCKED:open" in result.evidence["reason"]


def test_os_import_is_blocked(
    tmp_path: Path,
):
    result = execute_python_experiment(
        plan(
            """
import os
print("{}")
"""
        ),
        str(tmp_path),
    )

    assert result.executed is False
    assert "IMPORT_BLOCKED:os" in result.evidence["reason"]


def test_subprocess_import_is_blocked(
    tmp_path: Path,
):
    result = execute_python_experiment(
        plan(
            """
import subprocess
print("{}")
"""
        ),
        str(tmp_path),
    )

    assert result.executed is False
    assert (
        "IMPORT_BLOCKED:subprocess"
        in result.evidence["reason"]
    )
