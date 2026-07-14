from __future__ import annotations

from pathlib import Path

import pytest

from sophyane.graph_runtime import (
    Command,
    DurableStore,
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


def test_loop_and_recursion_limit(tmp_path: Path) -> None:
    graph = StateGraph(DurableStore(tmp_path / "graphs.db"))
    graph.add_node("increment", lambda state: {"counter": state["counter"] + 1})
    graph.add_edge(StateGraph.START, "increment")
    graph.add_conditional_edges(
        "increment",
        lambda state: "increment" if state["counter"] < 5 else StateGraph.END,
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


def test_retry_command_fanout_and_stream(tmp_path: Path) -> None:
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
        RetryPolicy(max_attempts=3, retry_exceptions=(TimeoutError,)),
    )
    graph.add_node("finish", lambda state: {"status": "success"})
    graph.add_edge(StateGraph.START, "connect")
    graph.add_edge("finish", StateGraph.END)

    result = graph.invoke({})
    assert attempts["count"] == 3
    assert result["connected"] is True
    assert result["status"] == "success"
    assert fan_out([2, 3, 5, 7], lambda value: value * value) == [4, 9, 25, 49]

    events = list(graph.stream({}))
    assert [event["node"] for event in events] == ["connect", "finish"]


def test_checkpoint_resume_and_namespaces(tmp_path: Path) -> None:
    store = DurableStore(tmp_path / "graphs.db")
    graph = StateGraph(store)
    graph.add_node("execute", lambda state: {"value": state["value"] * 3})
    graph.add_node("finalize", lambda state: {"value": state["value"] + 4})
    graph.add_edge(StateGraph.START, "execute")
    graph.add_edge("execute", "finalize")
    graph.add_edge("finalize", StateGraph.END)

    store.put(
        "checkpoint",
        "cp-1",
        {"state": {"value": 17}, "next_node": "execute", "trace": ["load", "validate"]},
    )
    result = graph.invoke({}, checkpoint_id="cp-1", resume=True)
    assert result["value"] == 55
    assert result["trace"] == ["load", "validate", "execute", "finalize"]

    store.put("thread", "A", {"value": "alpha"})
    store.put("thread", "B", {"value": "beta"})
    assert store.get("thread", "A") == {"value": "alpha"}
    assert store.get("thread", "B") == {"value": "beta"}
