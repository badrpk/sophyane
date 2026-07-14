from __future__ import annotations

import threading
import time
from pathlib import Path

from sophyane.multiagent import (
    ComplexityRouter,
    MultiAgentRuntime,
    MultiAgentStore,
)


class RecordingBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []
        self.lock = threading.Lock()

    def __call__(self, prompt: str, system_prompt: str) -> str:
        with self.lock:
            self.calls.append((prompt, system_prompt, threading.get_ident()))
        time.sleep(0.01)
        return f"completed: {system_prompt.split('.')[0]}"


def test_router_keeps_narrow_task_single() -> None:
    result = ComplexityRouter().assess("Fix this one Python syntax error")
    assert result.mode == "single_agent"
    assert result.roles == ("executor",)


def test_router_escalates_complex_project() -> None:
    result = ComplexityRouter().assess(
        "Build a complete backend API with authentication, database, tests, "
        "Docker deployment and documentation"
    )
    assert result.mode == "multi_agent"
    assert {"planner", "coder", "database", "security", "tester", "reviewer"} <= set(
        result.roles
    )


def test_forced_multi_launches_unique_workers_and_persists_trace(tmp_path: Path) -> None:
    backend = RecordingBackend()
    store = MultiAgentStore(tmp_path / "agents.db")
    runtime = MultiAgentRuntime(backend, store=store, max_workers=4)
    result = runtime.run("Build and test a calculator", mode="multi")

    assert result.mode == "multi_agent"
    assert len(result.workers) >= 3
    assert len({worker.worker_id for worker in result.workers}) == len(result.workers)
    assert all(worker.status == "completed" for worker in result.workers)
    assert result.supervisor_id.startswith("supervisor-")
    assert any(event["event_type"] == "workers_launched" for event in result.trace)
    persisted = store.inspect_run(result.run_id)
    assert persisted is not None
    assert len(persisted["workers"]) == len(result.workers)


def test_multi_workers_execute_on_more_than_one_thread(tmp_path: Path) -> None:
    backend = RecordingBackend()
    runtime = MultiAgentRuntime(
        backend,
        store=MultiAgentStore(tmp_path / "parallel.db"),
        max_workers=6,
    )
    runtime.run(
        "Build a complete API, database, security review, tests, documentation "
        "and deployment configuration",
        mode="multi",
    )
    thread_ids = {thread_id for _, _, thread_id in backend.calls[:-1]}
    assert len(thread_ids) > 1


def test_failed_worker_retries_and_is_recorded(tmp_path: Path) -> None:
    attempts = {"count": 0}

    def flaky(prompt: str, system_prompt: str) -> str:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise TimeoutError("temporary")
        return "recovered"

    runtime = MultiAgentRuntime(
        flaky,
        store=MultiAgentStore(tmp_path / "retry.db"),
        max_attempts=2,
    )
    result = runtime.run("Fix one syntax error", mode="single")
    assert result.workers[0].status == "completed"
    assert result.workers[0].attempts == 2
    assert result.final_output == "recovered"


def test_single_mode_uses_exactly_one_worker(tmp_path: Path) -> None:
    backend = RecordingBackend()
    result = MultiAgentRuntime(
        backend,
        store=MultiAgentStore(tmp_path / "single.db"),
    ).run("Write one SQL query", mode="single")
    assert result.mode == "single_agent"
    assert len(result.workers) == 1
    assert result.workers[0].role == "executor"
