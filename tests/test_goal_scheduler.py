from pathlib import Path

from sophyane.goal_execution import (
    GoalExecutor,
    GoalNode,
    ExecutionContext,
    ValidationResult,
    ActionResult,
)

from sophyane.goal_scheduler import ParallelGoalScheduler


def validator(context, goal):
    path = context.workspace / f"{goal.key}.txt"
    if path.exists():
        return ValidationResult(True)
    return ValidationResult(False)


def action(context, goal):
    (context.workspace / f"{goal.key}.txt").write_text("ok")
    return ActionResult(True, "done")


def test_parallel_scheduler(tmp_path: Path):

    goals = [
        GoalNode(
            key=f"goal{i}",
            description="",
            validator=validator,
            action=action,
        )
        for i in range(6)
    ]

    executor = GoalExecutor(
        ExecutionContext(tmp_path, "parallel"),
        goals,
    )

    scheduler = ParallelGoalScheduler(executor)

    stats = scheduler.run()

    assert stats.executed == 6
    assert executor.achieved()
