"""Structured observability for Sophyane goal-driven execution."""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .goal_execution import ExecutionEvent, ExecutionReport


FAILURE_CATEGORIES = (
    "generation",
    "validation",
    "repair",
    "runtime",
    "environment",
    "provider",
    "user_input",
    "unknown",
)


def classify_failure(
    text: str,
    *,
    event: str = "",
) -> str:
    """Classify an execution failure using stable, explainable rules."""
    value = f"{event} {text}".lower()

    rules = {
        "provider": (
            "provider",
            "api key",
            "quota",
            "rate limit",
            "http 429",
            "gemini",
            "local_gguf",
            "model response",
        ),
        "environment": (
            "module not found",
            "no module named",
            "permission denied",
            "command not found",
            "address already in use",
            "disk",
            "memory",
            "timeout",
            "timed out",
        ),
        "validation": (
            "validation",
            "validator",
            "syntax error",
            "missing html",
            "missing required",
            "incomplete html",
            "does not contain",
            "entry file",
        ),
        "repair": (
            "repair",
            "attempts exhausted",
            "could not repair",
            "unchanged artifact",
            "stagnation",
        ),
        "generation": (
            "generate",
            "generation",
            "artifact was not produced",
            "could not produce",
            "missing output",
        ),
        "user_input": (
            "invalid input",
            "unsupported request",
            "clarification required",
            "user cancelled",
        ),
        "runtime": (
            "runtime",
            "exception",
            "raised",
            "crash",
            "exit code",
            "execution stopped",
        ),
    }

    for category, markers in rules.items():
        if any(marker in value for marker in markers):
            return category

    return "unknown"


@dataclass(frozen=True)
class TraceRecord:
    trace_id: str
    timestamp: float
    request: str
    workspace: str
    cycle: int
    goal: str
    event: str
    status: str
    summary: str
    errors: tuple[str, ...]
    evidence: tuple[str, ...]
    category: str
    elapsed_ms: float | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class JsonlTraceWriter:
    """Thread-safe JSONL event writer suitable for long-running sessions."""

    def __init__(
        self,
        path: Path,
        *,
        request: str,
        workspace: Path,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.request = request
        self.workspace = str(Path(workspace).resolve())
        self.trace_id = trace_id or uuid.uuid4().hex
        self.metadata = dict(metadata or {})
        self.started = time.monotonic()
        self._lock = threading.Lock()

    def __call__(self, event: ExecutionEvent) -> None:
        """Accept an ExecutionEvent directly as a GoalExecutor event sink."""
        combined_errors = "; ".join(event.errors)
        category = (
            classify_failure(combined_errors or event.summary, event=event.event)
            if event.errors or "failed" in event.event or "exhausted" in event.event
            else ""
        )

        record = TraceRecord(
            trace_id=self.trace_id,
            timestamp=event.timestamp,
            request=self.request,
            workspace=self.workspace,
            cycle=event.cycle,
            goal=event.goal,
            event=event.event,
            status=event.status,
            summary=event.summary,
            errors=event.errors,
            evidence=event.evidence,
            category=category,
            elapsed_ms=round(
                (time.monotonic() - self.started) * 1000,
                3,
            ),
            metadata=self.metadata or None,
        )
        self.write(record)

    def write(self, record: TraceRecord) -> None:
        line = json.dumps(
            record.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
        )
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def read(self) -> tuple[dict[str, Any], ...]:
        if not self.path.is_file():
            return ()

        records: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            records.append(json.loads(line))
        return tuple(records)


@dataclass(frozen=True)
class RuntimeMetrics:
    achieved: bool
    cycles: int
    events_total: int
    goals_passed: int
    goals_failed: int
    goals_blocked: int
    goals_pending: int
    actions_started: int
    validation_passes: int
    validation_failures: int
    repair_attempts: int
    failure_categories: dict[str, int]
    elapsed_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def metrics_from_report(
    report: ExecutionReport,
    *,
    elapsed_ms: float | None = None,
) -> RuntimeMetrics:
    """Build deterministic metrics from an ExecutionReport."""
    event_counts = Counter(event.event for event in report.events)
    categories: Counter[str] = Counter()

    for event in report.events:
        if not event.errors and "failed" not in event.event:
            continue
        text = "; ".join(event.errors) or event.summary
        categories[classify_failure(text, event=event.event)] += 1

    repair_attempts = sum(
        1
        for event in report.events
        if event.event == "action_started"
        and "Attempt 1/" not in event.summary
    )

    return RuntimeMetrics(
        achieved=report.achieved,
        cycles=report.cycles,
        events_total=len(report.events),
        goals_passed=len(report.passed),
        goals_failed=len(report.failed),
        goals_blocked=len(report.blocked),
        goals_pending=len(report.pending),
        actions_started=event_counts["action_started"],
        validation_passes=event_counts["validation_passed"],
        validation_failures=event_counts["validation_failed"],
        repair_attempts=repair_attempts,
        failure_categories={
            category: categories.get(category, 0)
            for category in FAILURE_CATEGORIES
            if categories.get(category, 0)
        },
        elapsed_ms=elapsed_ms,
    )


def render_metrics(metrics: RuntimeMetrics) -> str:
    """Render a compact terminal summary."""
    status = "SUCCESS" if metrics.achieved else "FAILED"
    categories = ", ".join(
        f"{name}={count}"
        for name, count in metrics.failure_categories.items()
    ) or "none"

    lines = [
        "╭─ Sophyane Runtime Metrics",
        f"│ Status: {status}",
        f"│ Cycles: {metrics.cycles}",
        (
            "│ Goals: "
            f"passed={metrics.goals_passed} "
            f"failed={metrics.goals_failed} "
            f"blocked={metrics.goals_blocked} "
            f"pending={metrics.goals_pending}"
        ),
        (
            "│ Validation: "
            f"passed={metrics.validation_passes} "
            f"failed={metrics.validation_failures}"
        ),
        f"│ Actions: {metrics.actions_started}",
        f"│ Repairs: {metrics.repair_attempts}",
        f"│ Failure categories: {categories}",
    ]

    if metrics.elapsed_ms is not None:
        lines.append(f"│ Elapsed: {metrics.elapsed_ms:.1f} ms")

    lines.append("╰─")
    return "\n".join(lines)


def write_metrics(
    path: Path,
    metrics: RuntimeMetrics,
) -> Path:
    """Atomically write a metrics JSON document."""
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            metrics.to_dict(),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination
