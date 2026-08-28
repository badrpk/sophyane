from __future__ import annotations

from pathlib import Path

from sophyane.task_compiler import (
    Requirement,
    ground_requirement,
)


def test_workspace_parent_named_sophyane_runs_is_not_ignored(
    tmp_path: Path,
):
    outer = (
        tmp_path
        / "sophyane-runs"
        / "run-1"
        / "shop"
    )

    model = (
        outer
        / "shop"
        / "models.py"
    )

    model.parent.mkdir(
        parents=True
    )

    model.write_text(
        "class Order:\n"
        "    __tablename__ = 'orders'\n"
        "    user_id = Column(Integer)\n"
        "    status = Column(String)\n"
        "    created_at = Column(DateTime)\n",
        encoding="utf-8",
    )

    requirement = Requirement(
        requirement_id="r2",
        text=(
            "Add composite index on the orders table "
            "(user_id, status, created_at)"
        ),
        difficulty=3,
        explicit_facts=(
            "table:orders",
        ),
    )

    refs = ground_requirement(
        requirement,
        workspace=outer,
    )

    assert refs

    assert any(
        item.path
        == "shop/models.py"
        for item in refs
    )


def test_internal_ignored_directory_is_still_ignored(
    tmp_path: Path,
):
    root = (
        tmp_path
        / "workspace"
    )

    model = (
        root
        / "build"
        / "models.py"
    )

    model.parent.mkdir(
        parents=True
    )

    model.write_text(
        "class Order:\n"
        "    __tablename__ = 'orders'\n"
        "    user_id = Column(Integer)\n"
        "    status = Column(String)\n"
        "    created_at = Column(DateTime)\n",
        encoding="utf-8",
    )

    requirement = Requirement(
        requirement_id="r2",
        text=(
            "Add composite index on the orders table "
            "(user_id, status, created_at)"
        ),
        difficulty=3,
        explicit_facts=(
            "table:orders",
        ),
    )

    assert ground_requirement(
        requirement,
        workspace=root,
    ) == []
