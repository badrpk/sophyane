"""Safe builtin actions for the Sophyane cognitive loop.

SOPHYANE_COGNITIVE_SAFE_ACTIONS_V1

Only bounded non-destructive actions belong here.

No shell.
No arbitrary subprocess.
No financial transaction.
No hardware actuation.
No external publishing.
No credentials.
No self-replication.
No self-modification.
"""
from __future__ import annotations

from typing import Any, Mapping

from sophyane.cognitive_loop import (
    ActionResult,
    CognitiveTask,
    register_cognitive_action,
)


def hypothesis_only(
    task: CognitiveTask,
    context: Mapping[str, Any],
) -> ActionResult:
    """Represent an idea without pretending it was experimentally tested."""

    return ActionResult(
        ok=True,
        status="hypothesis_formed",
        observation={
            "hypothesis": task.payload.get(
                "hypothesis",
                task.objective,
            ),
            "executed": False,
        },
        evidence={
            "kind": "hypothesis_only",
            "verified": False,
        },
        metadata={
            "external_side_effect": False,
            "execution_authority": False,
        },
    )


def memory_inspection(
    task: CognitiveTask,
    context: Mapping[str, Any],
) -> ActionResult:
    from sophyane.cognitive_memory import (
        recall_sparse_memories,
    )

    query = str(
        task.payload.get(
            "query",
            task.objective,
        )
        or task.objective
    )

    rows = recall_sparse_memories(
        query,
        limit=8,
    )

    return ActionResult(
        ok=True,
        status="memory_inspected",
        observation={
            "count": len(rows),
            "memory_ids": [
                row.get(
                    "memory_id"
                )
                for row in rows
            ],
        },
        evidence={
            "rows": rows,
        },
        metadata={
            "external_side_effect": False,
            "read_only": True,
        },
    )


def install_safe_cognitive_actions() -> None:
    register_cognitive_action(
        "hypothesis_only",
        hypothesis_only,
    )

    register_cognitive_action(
        "memory_inspection",
        memory_inspection,
    )


install_safe_cognitive_actions()


__all__ = [
    "hypothesis_only",
    "install_safe_cognitive_actions",
    "memory_inspection",
]
