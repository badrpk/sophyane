from __future__ import annotations

from pathlib import Path
from typing import Any

import sophyane.unified_execution_kernel as kernel
from sophyane.readonly_task_graph import ReadonlyGraphNode


def _inventory(root: Path) -> tuple[str, ...]:
    return tuple(
        sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
        )
    )


def _success() -> kernel.ExecutionResult:
    return kernel.ExecutionResult(
        handled=True,
        ok=True,
        capability="test.success",
        output="success",
        evidence={},
        started_at=1.0,
        finished_at=2.0,
    )


def test_ordinary_execution_does_not_create_graph_database(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class Registry:
        def execute(self, request):
            del request
            return _success()

    monkeypatch.setattr(
        kernel,
        "initialize_registry",
        lambda: Registry(),
    )

    before = _inventory(tmp_path)

    result = kernel.execute_request(
        "ordinary request",
        workspace=tmp_path,
    )

    after = _inventory(tmp_path)

    assert result is not None
    assert result.ok is True
    assert before == after
    assert not (tmp_path / ".sophyane").exists()


def test_unhandled_request_does_not_mutate_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class Registry:
        def execute(self, request):
            del request
            return None

    monkeypatch.setattr(
        kernel,
        "initialize_registry",
        lambda: Registry(),
    )

    before = _inventory(tmp_path)

    result = kernel.execute_request(
        "unhandled request",
        workspace=tmp_path,
    )

    after = _inventory(tmp_path)

    assert result is None
    assert before == after
    assert not (tmp_path / ".sophyane").exists()


def test_readonly_graph_does_not_create_graph_database(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def worker() -> dict[str, Any]:
        calls.append("called")
        return {
            "ok": True,
            "value": "read-only",
        }

    node = ReadonlyGraphNode(
        node_id="read",
        worker=worker,
        read_only=True,
    )

    before = _inventory(tmp_path)

    result = kernel.execute_request(
        "read-only graph",
        workspace=tmp_path,
        metadata={
            "validated_readonly_graph_nodes": [node],
        },
    )

    after = _inventory(tmp_path)

    assert calls == ["called"]
    assert result is not None
    assert result.ok is True
    assert result.capability == "execution.readonly_task_graph"
    assert before == after
    assert not (tmp_path / ".sophyane").exists()


def test_empty_request_remains_mutation_free(
    tmp_path: Path,
) -> None:
    before = _inventory(tmp_path)

    result = kernel.execute_request(
        "",
        workspace=tmp_path,
    )

    after = _inventory(tmp_path)

    assert result is None
    assert before == after


def test_memory_store_supports_checkpoint_resume_without_filesystem(
    tmp_path: Path,
) -> None:
    from sophyane.graph_runtime import (
        GraphInterrupt,
        GraphResult,
        MemoryStore,
        StateGraph,
    )

    store = MemoryStore()
    graph = StateGraph(store)

    graph.add_node("first", lambda state: {"first": True})
    graph.add_node("second", lambda state: {"second": True})

    graph.add_edge(StateGraph.START, "first")
    graph.add_edge("first", "second")
    graph.add_edge("second", StateGraph.END)
    graph.set_interrupt_before("second")
    graph.compile()

    before = _inventory(tmp_path)

    try:
        graph.invoke(
            {},
            checkpoint_id="memory-checkpoint",
            recursion_limit=8,
            return_result=True,
        )
    except GraphInterrupt as exc:
        assert exc.node == "second"
        assert exc.checkpoint_id == "memory-checkpoint"
    else:
        raise AssertionError("expected GraphInterrupt")

    saved = graph.get_state("memory-checkpoint")

    assert saved is not None
    assert saved["next_node"] == "second"

    graph.interrupt_before.clear()

    result = graph.resume(
        "memory-checkpoint",
        recursion_limit=8,
        return_result=True,
    )

    after = _inventory(tmp_path)

    assert isinstance(result, GraphResult)
    assert result.completed is True
    assert result.state["first"] is True
    assert result.state["second"] is True
    assert before == after


def test_memory_store_checkpoint_is_snapshot_isolated() -> None:
    from sophyane.graph_runtime import MemoryStore

    store = MemoryStore()

    original = {
        "nested": {
            "values": [1, 2],
        },
    }

    store.put("checkpoint", "cp", original)

    original["nested"]["values"].append(3)

    saved = store.get("checkpoint", "cp")

    assert saved == {
        "nested": {
            "values": [1, 2],
        },
    }

    assert saved is not None
    saved["nested"]["values"].append(4)

    reread = store.get("checkpoint", "cp")

    assert reread == {
        "nested": {
            "values": [1, 2],
        },
    }
