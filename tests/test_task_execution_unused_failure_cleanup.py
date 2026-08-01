from __future__ import annotations

import ast
from pathlib import Path


def _tree() -> ast.Module:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "task_execution.py"
    ).read_text(encoding="utf-8")

    return ast.parse(source)


def test_no_plain_local_failure_assignments_remain() -> None:
    assignments = [
        node.lineno
        for node in ast.walk(_tree())
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "failure"
            for target in node.targets
        )
    ]

    assert assignments == []


def test_legitimate_annotated_failure_field_is_preserved() -> None:
    annotated_fields = [
        node.lineno
        for node in ast.walk(_tree())
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "failure"
    ]

    assert annotated_fields


def test_failure_evidence_is_still_recorded() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "task_execution.py"
    ).read_text(encoding="utf-8")

    assert "failed_action = action.action_id" in source
    assert "previous_failure = result.to_dict()" in source
    assert "all_results.append(result)" in source
