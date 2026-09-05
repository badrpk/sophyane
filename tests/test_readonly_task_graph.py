from __future__ import annotations

import time

import pytest

from sophyane.readonly_task_graph import (
    ReadonlyGraphNode,
    execute_readonly_task_graph,
)


def test_independent_nodes_run_in_parallel_and_dependents_follow() -> None:
    events: list[str] = []

    def first():
        events.append("a")
        return {"ok": True, "value": 1}

    def second():
        events.append("b")
        return {"ok": True, "value": 2}

    def combined():
        assert set(events) == {"a", "b"}
        return {"ok": True, "value": 3}

    result = execute_readonly_task_graph(
        [
            ReadonlyGraphNode("a", first),
            ReadonlyGraphNode("b", second),
            ReadonlyGraphNode("c", combined, ("a", "b")),
        ],
        max_workers=2,
    )

    assert result["ok"] is True
    assert result["completed"] == 3
    assert [node["node_id"] for node in result["nodes"]] == ["a", "b", "c"]


def test_worker_failure_blocks_dependents() -> None:
    calls: list[str] = []

    def failed():
        calls.append("failed")
        return {"ok": False, "error": "invalid evidence"}

    def dependent():
        calls.append("dependent")
        return {"ok": True}

    result = execute_readonly_task_graph(
        [
            ReadonlyGraphNode("failed", failed),
            ReadonlyGraphNode("dependent", dependent, ("failed",)),
        ]
    )

    assert result["ok"] is False
    assert calls == ["failed"]
    assert result["nodes"][0]["node_id"] == "dependent"
    assert result["nodes"][0]["skipped"] is True


def test_invalid_mutating_node_is_rejected() -> None:
    with pytest.raises(ValueError):
        execute_readonly_task_graph([ReadonlyGraphNode("write", lambda: {"ok": True}, read_only=False)])


def test_cycle_is_fail_closed() -> None:
    result = execute_readonly_task_graph(
        [
            ReadonlyGraphNode("a", lambda: {"ok": True}, ("b",)),
            ReadonlyGraphNode("b", lambda: {"ok": True}, ("a",)),
        ]
    )
    assert result["ok"] is False
    assert all(node["skipped"] for node in result["nodes"])


def test_deadline_is_bounded() -> None:
    def slow():
        time.sleep(0.05)
        return {"ok": True}

    result = execute_readonly_task_graph(
        [ReadonlyGraphNode("slow", slow)],
        deadline_seconds=0.01,
    )
    assert result["ok"] is False
    assert result["nodes"][0]["error"] == "graph deadline exceeded"


def test_duplicate_and_oversized_graphs_rejected() -> None:
    with pytest.raises(ValueError):
        execute_readonly_task_graph([ReadonlyGraphNode("a", lambda: {"ok": True}), ReadonlyGraphNode("a", lambda: {"ok": True})])
    with pytest.raises(ValueError):
        execute_readonly_task_graph([ReadonlyGraphNode(str(i), lambda: {"ok": True}) for i in range(33)])

def test_graph_deadline_is_one_absolute_wall_clock_budget() -> None:
    def blocked():
        time.sleep(0.20)
        return {"ok": True}

    nodes = [
        ReadonlyGraphNode(f"slow-{i}", blocked)
        for i in range(4)
    ]

    started = time.monotonic()
    result = execute_readonly_task_graph(
        nodes,
        max_workers=4,
        deadline_seconds=0.05,
    )
    elapsed = time.monotonic() - started

    assert result["ok"] is False
    assert elapsed < 0.15, (
        f"graph deadline multiplied across futures: "
        f"elapsed={elapsed:.3f}s for deadline=0.050s"
    )
    assert all(
        node["error"] == "graph deadline exceeded"
        for node in result["nodes"]
    )


def test_deadline_signals_cooperative_cancellation_to_running_worker() -> None:
    import threading

    cancel_event = threading.Event()
    started = threading.Event()
    stopped = threading.Event()

    def worker():
        started.set()
        while not cancel_event.wait(0.005):
            pass
        stopped.set()
        return {"ok": False, "error": "cancelled"}

    node = ReadonlyGraphNode(
        "cooperative",
        worker,
        cancel=cancel_event.set,
    )

    result = execute_readonly_task_graph(
        [node],
        max_workers=1,
        deadline_seconds=0.05,
    )

    assert started.is_set()
    assert result["ok"] is False
    assert result["nodes"][0]["error"] == "graph deadline exceeded"
    assert stopped.wait(0.10), (
        "running worker did not observe cooperative cancellation "
        "promptly after graph deadline"
    )


def test_cancellation_callback_failure_does_not_mask_graph_deadline() -> None:
    import threading

    started = threading.Event()
    release = threading.Event()

    def worker():
        started.set()
        release.wait(0.20)
        return {"ok": True}

    def broken_cancel():
        release.set()
        raise RuntimeError("cancel callback failed")

    result = execute_readonly_task_graph(
        [
            ReadonlyGraphNode(
                "cooperative",
                worker,
                cancel=broken_cancel,
            )
        ],
        max_workers=1,
        deadline_seconds=0.05,
    )

    assert started.is_set()
    assert result["ok"] is False
    assert result["nodes"][0]["error"] == "graph deadline exceeded"
