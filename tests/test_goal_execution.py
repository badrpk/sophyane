import json
from pathlib import Path

import pytest

from sophyane.goal_execution import (
    ActionResult,
    ExecutionContext,
    GoalExecutor,
    GoalGraphError,
    GoalNode,
    GoalStatus,
    ValidationResult,
    file_exists_validator,
    html_structure_validator,
    make_browser_goal_graph,
)


def test_existing_valid_goal_finishes_without_action(
    tmp_path: Path,
) -> None:
    target = tmp_path / "ready.txt"
    target.write_text("ready", encoding="utf-8")
    calls: list[str] = []

    def action(context, goal):
        calls.append(goal.key)
        return ActionResult(changed=True, summary="unexpected")

    executor = GoalExecutor(
        ExecutionContext(tmp_path, "Require ready.txt"),
        [
            GoalNode(
                key="ready",
                description="ready.txt exists",
                validator=file_exists_validator("ready.txt"),
                action=action,
            )
        ],
    )

    report = executor.run()

    assert report.achieved is True
    assert report.cycles == 0
    assert calls == []
    assert executor.goals["ready"].status is GoalStatus.PASSED


def test_missing_file_is_generated_and_validated(
    tmp_path: Path,
) -> None:
    def generate(context, goal):
        del goal
        (context.workspace / "result.txt").write_text(
            "generated",
            encoding="utf-8",
        )
        return ActionResult(
            changed=True,
            summary="Generated result.txt.",
            confidence=0.95,
        )

    executor = GoalExecutor(
        ExecutionContext(tmp_path, "Generate result"),
        [
            GoalNode(
                key="result",
                description="result.txt exists",
                validator=file_exists_validator("result.txt"),
                action=generate,
                max_attempts=2,
            )
        ],
    )

    report = executor.run()

    assert report.achieved is True
    assert report.cycles == 1
    assert (tmp_path / "result.txt").read_text() == "generated"


def test_failed_first_attempt_uses_repair(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def generate(context, goal):
        del goal
        calls.append("generate")
        (context.workspace / "index.html").write_text(
            "<h1>incomplete</h1>",
            encoding="utf-8",
        )
        return ActionResult(
            changed=True,
            summary="Generated incomplete HTML.",
        )

    def repair(context, goal):
        del goal
        calls.append("repair")
        (context.workspace / "index.html").write_text(
            "<!doctype html><html><body>OK</body></html>",
            encoding="utf-8",
        )
        return ActionResult(
            changed=True,
            summary="Repaired HTML.",
        )

    goals = make_browser_goal_graph(
        generate_html=generate,
        repair_html=repair,
    )
    executor = GoalExecutor(
        ExecutionContext(tmp_path, "Create browser app"),
        goals,
    )

    report = executor.run()

    assert report.achieved is True
    assert calls == ["generate", "repair"]
    assert executor.goals["browser_entry"].status is GoalStatus.PASSED
    assert executor.goals["html_structure"].status is GoalStatus.PASSED


def test_dependency_blocks_downstream_goal(
    tmp_path: Path,
) -> None:
    def always_fail(context, goal):
        del context, goal
        return ValidationResult(
            passed=False,
            errors=("permanent failure",),
            confidence=1.0,
            retryable=False,
        )

    def downstream_validator(context, goal):
        del context, goal
        pytest.fail("blocked validator must not run")

    executor = GoalExecutor(
        ExecutionContext(tmp_path, "Dependency test"),
        [
            GoalNode(
                key="foundation",
                description="Foundation",
                validator=always_fail,
                max_attempts=1,
            ),
            GoalNode(
                key="downstream",
                description="Downstream",
                validator=downstream_validator,
                dependencies=("foundation",),
            ),
        ],
    )

    report = executor.run()

    assert report.achieved is False
    assert executor.goals["foundation"].status is GoalStatus.EXHAUSTED
    assert executor.goals["downstream"].status is GoalStatus.BLOCKED


def test_attempt_limit_stops_infinite_repair(
    tmp_path: Path,
) -> None:
    calls = 0

    def validator(context, goal):
        del context, goal
        return ValidationResult(
            passed=False,
            errors=("still broken",),
            confidence=0.9,
        )

    def action(context, goal):
        nonlocal calls
        del context, goal
        calls += 1
        return ActionResult(
            changed=False,
            summary="Could not repair.",
            confidence=0.9,
        )

    executor = GoalExecutor(
        ExecutionContext(tmp_path, "Bound retries"),
        [
            GoalNode(
                key="broken",
                description="Never passes",
                validator=validator,
                action=action,
                repair=action,
                max_attempts=2,
            )
        ],
        max_cycles=10,
    )

    report = executor.run()

    assert report.achieved is False
    assert calls == 2
    assert executor.goals["broken"].status is GoalStatus.EXHAUSTED


def test_low_confidence_action_is_not_executed(
    tmp_path: Path,
) -> None:
    called = False

    def missing(context, goal):
        del context, goal
        return ValidationResult(
            passed=False,
            errors=("missing",),
            confidence=0.05,
        )

    def unsafe_action(context, goal):
        nonlocal called
        del context, goal
        called = True
        return ActionResult(changed=True, summary="unsafe")

    executor = GoalExecutor(
        ExecutionContext(tmp_path, "Do not guess"),
        [
            GoalNode(
                key="uncertain",
                description="Low-confidence goal",
                validator=missing,
                action=unsafe_action,
                confidence=0.05,
            )
        ],
        minimum_action_confidence=0.15,
    )

    report = executor.run()

    assert report.achieved is False
    assert called is False
    assert executor.goals["uncertain"].status is GoalStatus.EXHAUSTED


def test_checkpoint_contains_goal_evidence(
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "state.json"
    (tmp_path / "file.txt").write_text("yes", encoding="utf-8")

    executor = GoalExecutor(
        ExecutionContext(tmp_path, "Checkpoint test"),
        [
            GoalNode(
                key="file",
                description="file exists",
                validator=file_exists_validator("file.txt"),
            )
        ],
        checkpoint_path=checkpoint,
    )

    report = executor.run()
    state = json.loads(checkpoint.read_text(encoding="utf-8"))

    assert report.achieved is True
    assert state["achieved"] is True
    assert state["goals"]["file"]["status"] == "passed"
    assert state["goals"]["file"]["evidence"]


def test_unknown_dependency_is_rejected(
    tmp_path: Path,
) -> None:
    with pytest.raises(GoalGraphError, match="unknown dependencies"):
        GoalExecutor(
            ExecutionContext(tmp_path, "Invalid graph"),
            [
                GoalNode(
                    key="child",
                    description="Invalid dependency",
                    validator=file_exists_validator("x"),
                    dependencies=("missing",),
                )
            ],
        )


def test_dependency_cycle_is_rejected(
    tmp_path: Path,
) -> None:
    validator = file_exists_validator("x")

    with pytest.raises(GoalGraphError, match="dependency cycle"):
        GoalExecutor(
            ExecutionContext(tmp_path, "Cycle"),
            [
                GoalNode(
                    key="a",
                    description="A",
                    validator=validator,
                    dependencies=("b",),
                ),
                GoalNode(
                    key="b",
                    description="B",
                    validator=validator,
                    dependencies=("a",),
                ),
            ],
        )


def test_html_validator_rejects_fragment(
    tmp_path: Path,
) -> None:
    (tmp_path / "index.html").write_text(
        "<h1>fragment</h1>",
        encoding="utf-8",
    )

    result = html_structure_validator()(
        ExecutionContext(tmp_path, "HTML"),
        GoalNode(
            key="html",
            description="HTML structure",
            validator=html_structure_validator(),
        ),
    )

    assert result.passed is False
    assert "Missing DOCTYPE declaration." in result.errors
