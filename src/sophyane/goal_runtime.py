"""Compatibility bridge between legacy execution and the goal-driven runtime."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .goal_execution import (
    ExecutionContext,
    ExecutionReport,
    GoalExecutor,
    GoalNode,
)
from .post_build_menu import CompletionEvidence, PostBuildMenu, verify_completion


LegacyRunner = Callable[[], Any]


@dataclass(frozen=True)
class RuntimeResult:
    """Normalized result produced by goal-driven or legacy execution."""

    achieved: bool
    mode: str
    reason: str
    workspace: Path
    completion_evidence: CompletionEvidence
    goal_report: ExecutionReport | None = None
    legacy_result: Any = None

    @property
    def may_show_success_menu(self) -> bool:
        """Success requires runtime success and tangible completion evidence."""
        return self.achieved and self.completion_evidence.complete


def _normalize_goals(value: object) -> tuple[GoalNode, ...] | None:
    """Recognize goal output without confusing strings or mappings as goals."""
    if isinstance(value, GoalNode):
        return (value,)

    if isinstance(value, (str, bytes, dict)):
        return None

    if not isinstance(value, Iterable):
        return None

    items = tuple(value)
    if not items:
        return None

    if all(isinstance(item, GoalNode) for item in items):
        return items

    return None


def planner_goals(planner_output: object) -> tuple[GoalNode, ...] | None:
    """Extract goals from direct iterables or an object's ``goals`` attribute."""
    direct = _normalize_goals(planner_output)
    if direct is not None:
        return direct

    candidate = getattr(planner_output, "goals", None)
    return _normalize_goals(candidate)


def run_goal_runtime(
    *,
    request: str,
    workspace: Path,
    goals: Iterable[GoalNode],
    max_cycles: int = 50,
    metadata: dict[str, Any] | None = None,
) -> RuntimeResult:
    """Execute a goal graph and independently verify its final artifact."""
    context = ExecutionContext(
        workspace=Path(workspace),
        request=request,
        metadata=dict(metadata or {}),
    )
    executor = GoalExecutor(
        context,
        tuple(goals),
        max_cycles=max_cycles,
    )
    report = executor.run()
    evidence = verify_completion(context.workspace)

    achieved = report.achieved and evidence.complete
    if report.achieved and not evidence.complete:
        reason = (
            "Goal graph passed, but final completion evidence failed: "
            + "; ".join(evidence.errors)
        )
    else:
        reason = report.reason

    return RuntimeResult(
        achieved=achieved,
        mode="goal",
        reason=reason,
        workspace=context.workspace,
        completion_evidence=evidence,
        goal_report=report,
    )


def run_legacy_runtime(
    *,
    workspace: Path,
    legacy_runner: LegacyRunner,
) -> RuntimeResult:
    """Run legacy execution while enforcing the modern completion gate."""
    resolved = Path(workspace).resolve()

    try:
        legacy_result = legacy_runner()
    except Exception as error:  # noqa: BLE001
        evidence = verify_completion(resolved)
        return RuntimeResult(
            achieved=False,
            mode="legacy",
            reason=(
                f"Legacy execution raised {type(error).__name__}: {error}"
            ),
            workspace=resolved,
            completion_evidence=evidence,
        )

    evidence = verify_completion(resolved)

    explicit_failure = legacy_result is False
    achieved = not explicit_failure and evidence.complete

    if explicit_failure:
        reason = "Legacy runner explicitly reported failure."
    elif not evidence.complete:
        reason = (
            "Legacy runner returned, but completion evidence failed: "
            + "; ".join(evidence.errors)
        )
    else:
        reason = "Legacy execution passed the completion evidence gate."

    return RuntimeResult(
        achieved=achieved,
        mode="legacy",
        reason=reason,
        workspace=resolved,
        completion_evidence=evidence,
        legacy_result=legacy_result,
    )


def execute_planner_output(
    *,
    request: str,
    workspace: Path,
    planner_output: object,
    legacy_runner: LegacyRunner | None = None,
    max_cycles: int = 50,
    metadata: dict[str, Any] | None = None,
) -> RuntimeResult:
    """Use GoalExecutor when goals exist; otherwise preserve legacy behavior."""
    goals = planner_goals(planner_output)

    if goals is not None:
        return run_goal_runtime(
            request=request,
            workspace=workspace,
            goals=goals,
            max_cycles=max_cycles,
            metadata=metadata,
        )

    if legacy_runner is None:
        evidence = verify_completion(Path(workspace))
        return RuntimeResult(
            achieved=False,
            mode="unsupported",
            reason=(
                "Planner did not return GoalNode objects and no legacy "
                "runner was supplied."
            ),
            workspace=Path(workspace).resolve(),
            completion_evidence=evidence,
        )

    return run_legacy_runtime(
        workspace=workspace,
        legacy_runner=legacy_runner,
    )


def run_verified_post_build_menu(
    result: RuntimeResult,
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> str:
    """Show post-build actions only after authoritative runtime approval."""
    if not result.may_show_success_menu:
        output_fn("\n❌ Project is not complete.")
        output_fn(f"Mode: {result.mode}")
        output_fn(f"Reason: {result.reason}")
        for error in result.completion_evidence.errors:
            output_fn(f"- {error}")
        output_fn("Post-build success menu withheld.")
        return "incomplete"

    menu = PostBuildMenu(
        result.workspace,
        input_fn=input_fn,
        output_fn=output_fn,
    )
    return menu.run()
