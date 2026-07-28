from __future__ import annotations

from pathlib import Path

import pytest

from sophyane.graph_runtime import (
    Command,
    DurableStore,
    GraphDefinitionError,
    GraphInterrupt,
    GraphResult,
    RecursionLimitError,
    RetryPolicy,
    StateGraph,
    fan_out,
)


def test_sequential_and_conditional_execution(tmp_path: Path) -> None:
    graph = StateGraph(DurableStore(tmp_path / "graphs.db"))
    graph.add_node("load", lambda state: {"value": state["value"] + 2, "trace": ["load"]})
    graph.add_node("transform", lambda state: {"value": state["value"] * 5, "trace": ["transform"]})
    graph.add_node("validate", lambda state: {"valid": state["value"] == 30, "trace": ["validate"]})
    graph.add_edge(StateGraph.START, "load")
    graph.add_edge("load", "transform")
    graph.add_edge("transform", "validate")
    graph.add_edge("validate", StateGraph.END)

    result = graph.invoke({"value": 4, "trace": []})
    assert result == {
        "value": 30,
        "trace": ["load", "transform", "validate"],
        "valid": True,
    }


def test_loop_route_map_and_recursion_limit(tmp_path: Path) -> None:
    graph = StateGraph(DurableStore(tmp_path / "graphs.db"))
    graph.add_node("increment", lambda state: {"counter": state["counter"] + 1})
    graph.add_edge(StateGraph.START, "increment")
    graph.add_conditional_edges(
        "increment",
        lambda state: "again" if state["counter"] < 5 else "done",
        {"again": "increment", "done": StateGraph.END},
    )
    assert graph.invoke({"counter": 0})["counter"] == 5

    endless = StateGraph(DurableStore(tmp_path / "endless.db"))
    endless.add_node("a", lambda state: {})
    endless.add_node("b", lambda state: {})
    endless.add_edge(StateGraph.START, "a")
    endless.add_edge("a", "b")
    endless.add_edge("b", "a")
    with pytest.raises(RecursionLimitError):
        endless.invoke({}, recursion_limit=6)


def test_retry_command_parallel_fanout_and_stream(tmp_path: Path) -> None:
    attempts = {"count": 0}

    def unstable(state):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise TimeoutError("temporary")
        return Command(update={"connected": True}, goto="finish")

    graph = StateGraph(DurableStore(tmp_path / "graphs.db"))
    graph.add_node(
        "connect",
        unstable,
        RetryPolicy(max_attempts=3, retry_exceptions=(TimeoutError,), backoff=2),
    )
    graph.add_node("finish", lambda state: {"status": "success"})
    graph.add_edge(StateGraph.START, "connect")
    graph.add_edge("finish", StateGraph.END)

    result = graph.invoke({})
    assert attempts["count"] == 3
    assert result["connected"] is True
    assert result["status"] == "success"
    assert fan_out([2, 3, 5, 7], lambda value: value * value, max_workers=4) == [4, 9, 25, 49]

    events = list(graph.stream({}))
    assert [event["node"] for event in events] == ["connect", "finish"]
    assert all(event["elapsed_seconds"] >= 0 for event in events)


def test_checkpoint_resume_interrupt_and_telemetry(tmp_path: Path) -> None:
    store = DurableStore(tmp_path / "graphs.db")
    graph = StateGraph(store)
    graph.add_node("execute", lambda state: {"value": state["value"] * 3})
    graph.add_node("approve", lambda state: {"approved": True})
    graph.add_node("finalize", lambda state: {"value": state["value"] + 4})
    graph.add_edge(StateGraph.START, "execute")
    graph.add_edge("execute", "approve")
    graph.add_edge("approve", "finalize")
    graph.add_edge("finalize", StateGraph.END)
    graph.set_interrupt_before("approve")

    with pytest.raises(GraphInterrupt) as interrupted:
        graph.invoke({"value": 17}, checkpoint_id="cp-1")
    assert interrupted.value.node == "approve"
    saved = graph.get_state("cp-1")
    assert saved is not None
    assert saved["state"]["value"] == 51
    assert saved["next_node"] == "approve"

    result = graph.resume("cp-1", return_result=True)
    assert isinstance(result, GraphResult)
    assert result.state["value"] == 55
    assert result.state["approved"] is True
    assert result.trace == ["execute", "approve", "finalize"]
    assert [event.sequence for event in result.events] == [1, 2, 3]


def test_compile_rejects_invalid_graph(tmp_path: Path) -> None:
    graph = StateGraph(DurableStore(tmp_path / "graphs.db"))
    graph.add_node("work", lambda state: {})
    with pytest.raises(GraphDefinitionError):
        graph.compile()

    graph.add_edge(StateGraph.START, "missing")
    with pytest.raises(GraphDefinitionError):
        graph.compile()


def test_named_store_namespaces(tmp_path: Path) -> None:
    store = DurableStore(tmp_path / "graphs.db")
    store.put("thread", "A", {"value": "alpha"})
    store.put("thread", "B", {"value": "beta"})
    assert store.get("thread", "A") == {"value": "alpha"}
    assert store.get("thread", "B") == {"value": "beta"}
