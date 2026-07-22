"""Evidence-driven goal execution with validation, repair, and replanning."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class GoalStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    EXHAUSTED = "exhausted"


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    evidence: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    confidence: float = 1.0
    retryable: bool = True

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        if self.passed and self.errors:
            raise ValueError("a passing result cannot contain errors")


@dataclass(frozen=True)
class ActionResult:
    changed: bool
    summary: str
    evidence: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")


Validator = Callable[["ExecutionContext", "GoalNode"], ValidationResult]
Action = Callable[["ExecutionContext", "GoalNode"], ActionResult]


@dataclass
class GoalNode:
    key: str
    description: str
    validator: Validator
    action: Action | None = None
    repair: Action | None = None
    dependencies: tuple[str, ...] = ()
    required: bool = True
    priority: int = 100
    confidence: float = 0.5
    max_attempts: int = 3

    status: GoalStatus = GoalStatus.PENDING
    attempts: int = 0
    last_errors: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    last_summary: str = ""

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("goal key cannot be empty")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        if self.key in self.dependencies:
            raise ValueError(f"goal {self.key!r} cannot depend on itself")


@dataclass
class ExecutionEvent:
    timestamp: float
    cycle: int
    goal: str
    event: str
    status: str
    summary: str = ""
    errors: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()


@dataclass
class ExecutionContext:
    workspace: Path
    request: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.workspace = Path(self.workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class ExecutionReport:
    achieved: bool
    cycles: int
    reason: str
    passed: tuple[str, ...]
    failed: tuple[str, ...]
    blocked: tuple[str, ...]
    pending: tuple[str, ...]
    events: tuple[ExecutionEvent, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "achieved": self.achieved,
            "cycles": self.cycles,
            "reason": self.reason,
            "passed": list(self.passed),
            "failed": list(self.failed),
            "blocked": list(self.blocked),
            "pending": list(self.pending),
            "events": [asdict(event) for event in self.events],
        }


class GoalGraphError(RuntimeError):
    """Raised when the goal graph is structurally invalid."""


class GoalExecutor:
    """Continue selecting, executing, validating, and repairing until proven done."""

    def __init__(
        self,
        context: ExecutionContext,
        goals: Iterable[GoalNode],
        *,
        max_cycles: int = 50,
        checkpoint_path: Path | None = None,
        minimum_action_confidence: float = 0.15,
    ) -> None:
        if max_cycles < 1:
            raise ValueError("max_cycles must be at least 1")
        if not 0.0 <= minimum_action_confidence <= 1.0:
            raise ValueError(
                "minimum_action_confidence must be between 0.0 and 1.0"
            )

        self.context = context
        self.goals = {goal.key: goal for goal in goals}
        self.max_cycles = max_cycles
        self.minimum_action_confidence = minimum_action_confidence
        self.checkpoint_path = (
            Path(checkpoint_path).resolve()
            if checkpoint_path
            else context.workspace / ".sophyane-goal-state.json"
        )
        self.events: list[ExecutionEvent] = []
        self.cycle = 0

        self._validate_graph()

    def _validate_graph(self) -> None:
        if not self.goals:
            raise GoalGraphError("at least one goal is required")

        for goal in self.goals.values():
            missing = [
                dependency
                for dependency in goal.dependencies
                if dependency not in self.goals
            ]
            if missing:
                raise GoalGraphError(
                    f"goal {goal.key!r} has unknown dependencies: "
                    + ", ".join(missing)
                )

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(key: str) -> None:
            if key in visiting:
                raise GoalGraphError(f"dependency cycle detected at {key!r}")
            if key in visited:
                return

            visiting.add(key)
            for dependency in self.goals[key].dependencies:
                visit(dependency)
            visiting.remove(key)
            visited.add(key)

        for key in self.goals:
            visit(key)

    def _record(
        self,
        goal: GoalNode,
        event: str,
        *,
        summary: str = "",
        errors: tuple[str, ...] = (),
        evidence: tuple[str, ...] = (),
    ) -> None:
        self.events.append(
            ExecutionEvent(
                timestamp=time.time(),
                cycle=self.cycle,
                goal=goal.key,
                event=event,
                status=goal.status.value,
                summary=summary,
                errors=errors,
                evidence=evidence,
            )
        )

    def _dependencies_passed(self, goal: GoalNode) -> bool:
        return all(
            self.goals[key].status is GoalStatus.PASSED
            for key in goal.dependencies
        )

    def _dependency_permanently_failed(self, goal: GoalNode) -> bool:
        terminal = {GoalStatus.EXHAUSTED, GoalStatus.BLOCKED}
        return any(
            self.goals[key].status in terminal
            for key in goal.dependencies
        )

    def _refresh_states(self) -> None:
        for goal in self.goals.values():
            if goal.status in {
                GoalStatus.PASSED,
                GoalStatus.RUNNING,
                GoalStatus.EXHAUSTED,
            }:
                continue

            if self._dependency_permanently_failed(goal):
                goal.status = GoalStatus.BLOCKED
                goal.last_errors = (
                    "A required dependency did not complete successfully.",
                )
                continue

            if self._dependencies_passed(goal):
                goal.status = GoalStatus.READY
            else:
                goal.status = GoalStatus.PENDING

    def _validate_goal(self, goal: GoalNode) -> ValidationResult:
        try:
            result = goal.validator(self.context, goal)
        except Exception as error:  # noqa: BLE001
            result = ValidationResult(
                passed=False,
                errors=(
                    f"Validator raised {type(error).__name__}: {error}",
                ),
                confidence=0.0,
                retryable=True,
            )

        goal.confidence = result.confidence
        goal.evidence = result.evidence
        goal.last_errors = result.errors

        if result.passed:
            goal.status = GoalStatus.PASSED
            self._record(
                goal,
                "validation_passed",
                summary="Goal passed validation.",
                evidence=result.evidence,
            )
        else:
            goal.status = GoalStatus.FAILED
            self._record(
                goal,
                "validation_failed",
                summary="Goal has an unresolved gap.",
                errors=result.errors,
                evidence=result.evidence,
            )
            if not result.retryable:
                goal.status = GoalStatus.EXHAUSTED

        return result

    def validate_all(self) -> None:
        """Recheck completed and currently actionable goals against evidence."""
        self._refresh_states()

        for goal in sorted(
            self.goals.values(),
            key=lambda item: (item.priority, item.key),
        ):
            if goal.status in {
                GoalStatus.BLOCKED,
                GoalStatus.EXHAUSTED,
            }:
                continue
            if not self._dependencies_passed(goal):
                continue
            self._validate_goal(goal)

        self._refresh_states()

    def unresolved_gaps(self) -> tuple[GoalNode, ...]:
        required = [
            goal
            for goal in self.goals.values()
            if goal.required and goal.status is not GoalStatus.PASSED
        ]
        return tuple(
            sorted(
                required,
                key=lambda goal: (
                    goal.priority,
                    goal.attempts,
                    -goal.confidence,
                    goal.key,
                ),
            )
        )

    def choose_next_goal(self) -> GoalNode | None:
        self._refresh_states()

        candidates = [
            goal
            for goal in self.goals.values()
            if goal.status in {GoalStatus.READY, GoalStatus.FAILED}
            and self._dependencies_passed(goal)
            and goal.attempts < goal.max_attempts
        ]

        if not candidates:
            return None

        # Lowest priority number wins. Within the same priority, prefer:
        # 1. fewer attempts,
        # 2. greater confidence,
        # 3. stable lexical ordering.
        return min(
            candidates,
            key=lambda goal: (
                goal.priority,
                goal.attempts,
                -goal.confidence,
                goal.key,
            ),
        )

    def _execute_action(self, goal: GoalNode) -> ActionResult:
        # First attempt uses the primary action.
        # Subsequent attempts use the repair action if one exists.
        is_repair = goal.attempts > 1
        action = goal.repair if is_repair and goal.repair else goal.action

        if action is None:
            return ActionResult(
                changed=False,
                summary="No action is registered for this unresolved goal.",
                errors=("No executable action is available.",),
                confidence=0.0,
            )

        try:
            return action(self.context, goal)
        except Exception as error:  # noqa: BLE001
            return ActionResult(
                changed=False,
                summary=f"Action raised {type(error).__name__}.",
                errors=(str(error),),
                confidence=0.0,
            )

    def execute_one(self, goal: GoalNode) -> None:
        goal.attempts += 1
        goal.status = GoalStatus.RUNNING

        self._record(
            goal,
            "action_started",
            summary=f"Attempt {goal.attempts}/{goal.max_attempts}.",
        )

        action_result = self._execute_action(goal)
        goal.last_summary = action_result.summary
        goal.confidence = action_result.confidence

        self._record(
            goal,
            "action_finished",
            summary=action_result.summary,
            errors=action_result.errors,
            evidence=action_result.evidence,
        )

        validation = self._validate_goal(goal)

        if not validation.passed and goal.attempts >= goal.max_attempts:
            goal.status = GoalStatus.EXHAUSTED
            self._record(
                goal,
                "attempts_exhausted",
                summary=(
                    f"Goal exhausted its {goal.max_attempts} "
                    "permitted attempts."
                ),
                errors=goal.last_errors,
            )

    def achieved(self) -> bool:
        return all(
            not goal.required or goal.status is GoalStatus.PASSED
            for goal in self.goals.values()
        )

    def _state_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "request": self.context.request,
            "workspace": str(self.context.workspace),
            "cycle": self.cycle,
            "max_cycles": self.max_cycles,
            "achieved": self.achieved(),
            "goals": {
                key: {
                    "description": goal.description,
                    "required": goal.required,
                    "dependencies": list(goal.dependencies),
                    "priority": goal.priority,
                    "status": goal.status.value,
                    "attempts": goal.attempts,
                    "max_attempts": goal.max_attempts,
                    "confidence": goal.confidence,
                    "last_errors": list(goal.last_errors),
                    "evidence": list(goal.evidence),
                    "last_summary": goal.last_summary,
                }
                for key, goal in self.goals.items()
            },
            "events": [asdict(event) for event in self.events],
            "updated_at": time.time(),
        }

    def save_checkpoint(self) -> None:
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.checkpoint_path.with_suffix(
            self.checkpoint_path.suffix + ".tmp"
        )
        temporary.write_text(
            json.dumps(
                self._state_dict(),
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.checkpoint_path)

    def report(self, reason: str) -> ExecutionReport:
        groups: dict[GoalStatus, list[str]] = {
            status: [] for status in GoalStatus
        }
        for goal in self.goals.values():
            groups[goal.status].append(goal.key)

        return ExecutionReport(
            achieved=self.achieved(),
            cycles=self.cycle,
            reason=reason,
            passed=tuple(sorted(groups[GoalStatus.PASSED])),
            failed=tuple(
                sorted(
                    groups[GoalStatus.FAILED]
                    + groups[GoalStatus.EXHAUSTED]
                )
            ),
            blocked=tuple(sorted(groups[GoalStatus.BLOCKED])),
            pending=tuple(
                sorted(
                    groups[GoalStatus.PENDING]
                    + groups[GoalStatus.READY]
                    + groups[GoalStatus.RUNNING]
                )
            ),
            events=tuple(self.events),
        )

    def run(self) -> ExecutionReport:
        """Act until every required goal is proven or progress is impossible."""
        self.validate_all()
        self.save_checkpoint()

        if self.achieved():
            return self.report("All required goals already passed validation.")

        while self.cycle < self.max_cycles:
            self.cycle += 1
            goal = self.choose_next_goal()

            if goal is None:
                self.save_checkpoint()
                return self.report(
                    "No executable goal remains; unresolved goals are "
                    "blocked or exhausted."
                )

            if goal.confidence < self.minimum_action_confidence:
                goal.status = GoalStatus.EXHAUSTED
                goal.last_errors = (
                    "Action confidence fell below the configured safety floor.",
                )
                self._record(
                    goal,
                    "confidence_floor",
                    summary="Unsafe low-confidence action was not executed.",
                    errors=goal.last_errors,
                )
            else:
                self.execute_one(goal)

            self._refresh_states()
            self.save_checkpoint()

            if self.achieved():
                return self.report(
                    "All required goals passed evidence-based validation."
                )

        return self.report("Maximum execution cycles reached.")


def file_exists_validator(relative_path: str) -> Validator:
    """Build a validator requiring a non-empty file."""

    def validate(
        context: ExecutionContext,
        goal: GoalNode,
    ) -> ValidationResult:
        del goal
        path = context.workspace / relative_path

        if not path.is_file():
            return ValidationResult(
                passed=False,
                errors=(f"Missing required file: {relative_path}",),
                confidence=0.95,
            )

        size = path.stat().st_size
        if size <= 0:
            return ValidationResult(
                passed=False,
                errors=(f"Required file is empty: {relative_path}",),
                confidence=0.95,
            )

        return ValidationResult(
            passed=True,
            evidence=(f"{relative_path} exists ({size} bytes).",),
            confidence=1.0,
        )

    return validate


def html_structure_validator(
    relative_path: str = "index.html",
) -> Validator:
    """Build a structural validator for a standalone HTML document."""

    def validate(
        context: ExecutionContext,
        goal: GoalNode,
    ) -> ValidationResult:
        del goal
        path = context.workspace / relative_path

        if not path.is_file():
            return ValidationResult(
                passed=False,
                errors=(f"Missing HTML entry: {relative_path}",),
                confidence=0.98,
            )

        text = path.read_text(encoding="utf-8", errors="ignore")
        lowered = text.lower()
        errors: list[str] = []

        required_fragments = {
            "<!doctype html": "DOCTYPE declaration",
            "<html": "<html> element",
            "<body": "<body> element",
            "</html>": "closing </html> element",
        }

        for fragment, label in required_fragments.items():
            if fragment not in lowered:
                errors.append(f"Missing {label}.")

        if errors:
            return ValidationResult(
                passed=False,
                errors=tuple(errors),
                evidence=(f"Inspected {relative_path}.",),
                confidence=0.96,
            )

        return ValidationResult(
            passed=True,
            evidence=(
                f"{relative_path} is a complete HTML document "
                f"({len(text.encode('utf-8'))} bytes).",
            ),
            confidence=1.0,
        )

    return validate


def python_syntax_validator(
    relative_path: str = "main.py",
) -> Validator:
    """Build a validator requiring syntactically valid Python."""

    def validate(
        context: ExecutionContext,
        goal: GoalNode,
    ) -> ValidationResult:
        del goal
        path = context.workspace / relative_path

        if not path.is_file():
            return ValidationResult(
                passed=False,
                errors=(f"Missing Python entry: {relative_path}",),
                confidence=0.98,
            )

        source = path.read_text(encoding="utf-8", errors="ignore")
        try:
            compile(source, str(path), "exec")
        except SyntaxError as error:
            return ValidationResult(
                passed=False,
                errors=(
                    f"Python syntax error at line "
                    f"{error.lineno}: {error.msg}",
                ),
                confidence=0.99,
            )

        return ValidationResult(
            passed=True,
            evidence=(f"{relative_path} passed Python compilation.",),
            confidence=1.0,
        )

    return validate


def make_browser_goal_graph(
    *,
    generate_html: Action,
    repair_html: Action | None = None,
    extra_goals: Iterable[GoalNode] = (),
) -> tuple[GoalNode, ...]:
    """Create the minimum evidence graph for a browser deliverable."""
    goals = [
        GoalNode(
            key="browser_entry",
            description="A non-empty index.html exists.",
            validator=file_exists_validator("index.html"),
            action=generate_html,
            repair=repair_html or generate_html,
            priority=10,
            confidence=0.9,
            max_attempts=3,
        ),
        GoalNode(
            key="html_structure",
            description="index.html is a complete HTML document.",
            validator=html_structure_validator("index.html"),
            action=repair_html or generate_html,
            repair=repair_html or generate_html,
            dependencies=("browser_entry",),
            priority=20,
            confidence=0.9,
            max_attempts=3,
        ),
    ]
    goals.extend(extra_goals)
    return tuple(goals)


def report_summary(report: ExecutionReport) -> str:
    """Return a concise human-readable completion summary."""
    lines = [
        (
            "✅ Goal achieved"
            if report.achieved
            else "❌ Goal not achieved"
        ),
        f"Cycles: {report.cycles}",
        f"Reason: {report.reason}",
        f"Passed: {', '.join(report.passed) or 'none'}",
        f"Failed: {', '.join(report.failed) or 'none'}",
        f"Blocked: {', '.join(report.blocked) or 'none'}",
        f"Pending: {', '.join(report.pending) or 'none'}",
    ]
    return "\n".join(lines)
