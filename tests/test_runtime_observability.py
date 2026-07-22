import json
from pathlib import Path

from sophyane.goal_execution import (
    ActionResult,
    ExecutionContext,
    GoalExecutor,
    GoalNode,
    ValidationResult,
    file_exists_validator,
)
from sophyane.runtime_observability import (
    JsonlTraceWriter,
    classify_failure,
    metrics_from_report,
    render_metrics,
    write_metrics,
)


def test_failure_classifier() -> None:
    assert classify_failure("Gemini API key missing") == "provider"
    assert classify_failure("No module named pytest") == "environment"
    assert classify_failure("HTML validation failed") == "validation"
    assert classify_failure("Repair attempts exhausted") == "repair"
    assert classify_failure("Generation produced no artifact") == "generation"
    assert classify_failure("Unexpected exception") == "runtime"
    assert classify_failure("something unfamiliar") == "unknown"


def test_goal_executor_streams_jsonl_events(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    writer = JsonlTraceWriter(
        trace_path,
        request="Create result",
        workspace=tmp_path,
        metadata={"provider": "test"},
    )

    def generate(context, goal):
        del goal
        (context.workspace / "result.txt").write_text(
            "ready",
            encoding="utf-8",
        )
        return ActionResult(
            changed=True,
            summary="Generated result.",
            confidence=1.0,
        )

    executor = GoalExecutor(
        ExecutionContext(tmp_path, "Create result"),
        [
            GoalNode(
                key="result",
                description="result exists",
                validator=file_exists_validator("result.txt"),
                action=generate,
            )
        ],
        event_sink=writer,
    )

    report = executor.run()
    records = writer.read()

    assert report.achieved is True
    assert records
    assert any(record["event"] == "action_started" for record in records)
    assert any(
        record["event"] == "validation_passed"
        for record in records
    )
    assert all(record["trace_id"] == writer.trace_id for record in records)
    assert records[0]["metadata"]["provider"] == "test"


def test_broken_trace_sink_never_breaks_execution(
    tmp_path: Path,
) -> None:
    def broken_sink(event):
        del event
        raise RuntimeError("trace disk unavailable")

    def generate(context, goal):
        del goal
        (context.workspace / "ok.txt").write_text(
            "ok",
            encoding="utf-8",
        )
        return ActionResult(changed=True, summary="done")

    executor = GoalExecutor(
        ExecutionContext(tmp_path, "Safe telemetry"),
        [
            GoalNode(
                key="ok",
                description="ok exists",
                validator=file_exists_validator("ok.txt"),
                action=generate,
            )
        ],
        event_sink=broken_sink,
    )

    assert executor.run().achieved is True


def test_metrics_summarize_repairs_and_failures(
    tmp_path: Path,
) -> None:
    attempts = 0

    def validator(context, goal):
        del context, goal
        if attempts < 2:
            return ValidationResult(
                passed=False,
                errors=("HTML validation failed: missing body",),
                confidence=0.9,
            )
        return ValidationResult(
            passed=True,
            evidence=("HTML structure verified.",),
            confidence=1.0,
        )

    def action(context, goal):
        nonlocal attempts
        del context, goal
        attempts += 1
        return ActionResult(
            changed=True,
            summary=f"Attempted repair {attempts}.",
            confidence=0.9,
        )

    executor = GoalExecutor(
        ExecutionContext(tmp_path, "Repair HTML"),
        [
            GoalNode(
                key="html",
                description="HTML passes",
                validator=validator,
                action=action,
                repair=action,
                max_attempts=3,
            )
        ],
    )

    report = executor.run()
    metrics = metrics_from_report(report, elapsed_ms=12.5)

    assert report.achieved is True
    assert metrics.validation_failures >= 1
    assert metrics.validation_passes >= 1
    assert metrics.actions_started == 2
    assert metrics.repair_attempts == 1
    assert metrics.failure_categories["validation"] >= 1
    assert "Status: SUCCESS" in render_metrics(metrics)


def test_metrics_json_is_written_atomically(
    tmp_path: Path,
) -> None:
    executor = GoalExecutor(
        ExecutionContext(tmp_path, "Existing file"),
        [
            GoalNode(
                key="file",
                description="file exists",
                validator=file_exists_validator("file.txt"),
                action=lambda context, goal: ActionResult(
                    changed=True,
                    summary="created",
                ),
            )
        ],
    )

    (tmp_path / "file.txt").write_text("yes", encoding="utf-8")
    metrics = metrics_from_report(executor.run())
    destination = write_metrics(tmp_path / "metrics.json", metrics)
    payload = json.loads(destination.read_text(encoding="utf-8"))

    assert payload["achieved"] is True
    assert payload["goals_passed"] == 1
    assert not (tmp_path / "metrics.json.tmp").exists()
