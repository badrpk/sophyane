from __future__ import annotations

from pathlib import Path

from sophyane.task_compiler import (
    Evidence,
    Requirement,
    build_execution_plan,
    ground_requirement,
    grounding_required,
)


def test_database_index_requires_grounding():
    requirement = Requirement(
        requirement_id="r1",
        text=(
            "Add composite index on the orders table "
            "(user_id, status, created_at)"
        ),
        difficulty=3,
    )

    assert grounding_required(
        requirement
    )


def test_grounding_search_returns_only_real_workspace_paths(
    tmp_path: Path,
):
    target = (
        tmp_path
        / "models"
        / "order.py"
    )

    target.parent.mkdir(
        parents=True
    )

    target.write_text(
        "class Order:\n"
        "    user_id = 1\n"
        "    status = 'new'\n"
        "    created_at = None\n",
        encoding="utf-8",
    )

    requirement = Requirement(
        requirement_id="r1",
        text=(
            "Add composite index on the orders table "
            "(user_id, status, created_at)"
        ),
        difficulty=3,
    )

    groundings = ground_requirement(
        requirement,
        workspace=tmp_path,
    )

    assert groundings

    for grounding in groundings:
        assert (
            tmp_path
            / grounding.path
        ).exists()


def test_execution_plan_requires_valid_evidence_and_grounding():
    requirement = Requirement(
        requirement_id="r1",
        text=(
            "Add composite index on the orders table "
            "(user_id, status, created_at)"
        ),
        difficulty=3,
    )

    evidence = {
        "r1": Evidence(
            value=(
                "CREATE INDEX idx_orders "
                "ON orders "
                "(user_id, status, created_at);"
            ),
            provenance="LOCAL_LLM",
            valid=True,
        )
    }

    assert build_execution_plan(
        [requirement],
        evidence,
        {"r1": []},
    ) == []


def test_execution_plan_binds_real_target():
    requirement = Requirement(
        requirement_id="r1",
        text=(
            "Add composite index on the orders table "
            "(user_id, status, created_at)"
        ),
        difficulty=3,
    )

    evidence = {
        "r1": Evidence(
            value=(
                "CREATE INDEX idx_orders "
                "ON orders "
                "(user_id, status, created_at);"
            ),
            provenance="LOCAL_LLM",
            valid=True,
        )
    }

    from sophyane.task_compiler import Grounding

    plan = build_execution_plan(
        [requirement],
        evidence,
        {
            "r1": [
                Grounding(
                    requirement_id="r1",
                    path="models/order.py",
                    kind="model_or_schema",
                    score=5.0,
                )
            ]
        },
    )

    assert len(plan) == 1
    assert (
        plan[0]["operation"]
        == "modify_schema_or_migration"
    )
    assert (
        plan[0]["targets"][0]["path"]
        == "models/order.py"
    )
    assert plan[0]["dry_run"] is True
