from pathlib import Path

from sophyane.failure_memory import (
    CompositeEventSink,
    FailureMemory,
    SuccessfulRepairObserver,
    failure_fingerprint,
    normalize_failure,
    suggested_repair_context,
)
from sophyane.goal_execution import ExecutionEvent


def event(
    name: str,
    *,
    goal: str = "html",
    summary: str = "",
    errors: tuple[str, ...] = (),
) -> ExecutionEvent:
    return ExecutionEvent(
        timestamp=1.0,
        cycle=1,
        goal=goal,
        event=name,
        status="ready",
        summary=summary,
        errors=errors,
        evidence=(),
    )


def test_normalization_removes_unstable_values() -> None:
    first = normalize_failure(
        "Missing file /tmp/build-123/index.html at line 42"
    )
    second = normalize_failure(
        "Missing file /tmp/build-999/index.html at line 77"
    )

    assert first == second
    assert failure_fingerprint(first) == failure_fingerprint(second)


def test_memory_stores_and_retrieves_successful_repair(
    tmp_path: Path,
) -> None:
    memory = FailureMemory(tmp_path / "repairs.jsonl")

    memory.remember_success(
        error="HTML validation failed: missing body",
        repair_summary="Added a complete body element.",
        goal="html",
        provider="gemini",
        confidence=0.94,
    )

    match = memory.best_repair(
        "HTML validation failed: missing body",
        goal="html",
    )

    assert match is not None
    assert match.similarity == 1.0
    assert match.memory.provider == "gemini"
    assert "complete body" in match.memory.repair_summary


def test_duplicate_memory_is_not_appended(
    tmp_path: Path,
) -> None:
    memory = FailureMemory(tmp_path / "repairs.jsonl")

    for _ in range(2):
        memory.remember_success(
            error="Missing closing HTML tag",
            repair_summary="Added the closing html tag.",
            goal="document",
        )

    assert len(memory.entries()) == 1


def test_observer_records_only_after_validation_passes(
    tmp_path: Path,
) -> None:
    memory = FailureMemory(tmp_path / "repairs.jsonl")
    observer = SuccessfulRepairObserver(
        memory,
        provider="test-provider",
    )

    observer(
        event(
            "validation_failed",
            errors=("HTML validation failed: missing body",),
        )
    )
    observer(
        event(
            "action_started",
            summary="Add the missing body element.",
        )
    )

    assert memory.entries() == ()

    observer(
        event(
            "validation_passed",
            summary="HTML structure verified.",
        )
    )

    entries = memory.entries()
    assert len(entries) == 1
    assert entries[0].provider == "test-provider"
    assert entries[0].goal == "html"


def test_failed_repair_is_not_remembered(
    tmp_path: Path,
) -> None:
    memory = FailureMemory(tmp_path / "repairs.jsonl")
    observer = SuccessfulRepairObserver(memory)

    observer(
        event(
            "validation_failed",
            errors=("JavaScript syntax error",),
        )
    )
    observer(
        event(
            "action_started",
            summary="Attempt syntax repair.",
        )
    )
    observer(
        event(
            "goal_exhausted",
            summary="Repair attempts exhausted.",
        )
    )

    assert memory.entries() == ()


def test_similar_failure_returns_prior_repair(
    tmp_path: Path,
) -> None:
    memory = FailureMemory(tmp_path / "repairs.jsonl")

    memory.remember_success(
        error="Validation failed at line 42: missing body element",
        repair_summary="Insert a body element around page content.",
        goal="html",
    )

    match = memory.best_repair(
        "Validation failed at line 99: missing body element",
        goal="html",
        minimum_similarity=0.65,
    )

    assert match is not None
    assert match.similarity >= 0.65


def test_prompt_context_contains_proven_repair(
    tmp_path: Path,
) -> None:
    memory = FailureMemory(tmp_path / "repairs.jsonl")

    memory.remember_success(
        error="Incomplete HTML document",
        repair_summary="Generated doctype, html, head, and body.",
        goal="html",
    )

    context = suggested_repair_context(
        memory,
        "Incomplete HTML document",
        goal="html",
    )

    assert "repaired successfully before" in context
    assert "doctype" in context
    assert "still validate" in context


def test_composite_sink_isolates_broken_observer() -> None:
    received: list[str] = []

    def broken(item: ExecutionEvent) -> None:
        del item
        raise RuntimeError("observer unavailable")

    def working(item: ExecutionEvent) -> None:
        received.append(item.event)

    sink = CompositeEventSink(broken, working)
    sink(event("validation_passed"))

    assert received == ["validation_passed"]
