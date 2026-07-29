"""LangGraph-like state management for Sophyane (zero extra deps).

Concepts
--------
- State is a plain dict (or any mapping).
- Nodes are callables: (state) -> partial state update (dict) or full state.
- Edges connect nodes; conditional edges choose the next node from state.
- START / END bookend the graph.
- invoke() runs to completion; stream() yields state after each node.
- MemorySaver checkpoints thread state between invokes (optional).

This is intentionally small. It is not a full Pregel reimplementation.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Mapping, MutableMapping

START = "__start__"
END = "__end__"

NodeFn = Callable[[dict[str, Any]], Mapping[str, Any] | None]
ConditionFn = Callable[[dict[str, Any]], str]


def _merge(state: dict[str, Any], update: Mapping[str, Any] | None) -> dict[str, Any]:
    if not update:
        return state
    out = dict(state)
    for key, value in update.items():
        # List channels append when both sides are lists (reducer-lite).
        if isinstance(value, list) and isinstance(out.get(key), list):
            out[key] = list(out[key]) + list(value)
        else:
            out[key] = value
    return out


@dataclass
class MemorySaver:
    """In-memory checkpoint store keyed by thread_id."""

    _store: dict[str, dict[str, Any]] = field(default_factory=dict)

    def get(self, thread_id: str) -> dict[str, Any] | None:
        data = self._store.get(thread_id)
        return deepcopy(data) if data is not None else None

    def put(self, thread_id: str, state: Mapping[str, Any]) -> None:
        self._store[thread_id] = deepcopy(dict(state))

    def clear(self, thread_id: str | None = None) -> None:
        if thread_id is None:
            self._store.clear()
        else:
            self._store.pop(thread_id, None)


class StateGraph:
    """Builder for a directed state machine over a shared dict state."""

    def __init__(self, channels: type | None = None) -> None:
        # channels is optional documentation/typing hint only (dict runtime).
        self._channels = channels
        self._nodes: dict[str, NodeFn] = {}
        self._edges: dict[str, str] = {}
        self._conditional: dict[str, tuple[ConditionFn, dict[str, str]]] = {}
        self._entry: str | None = None

    def add_node(self, name: str, fn: NodeFn) -> StateGraph:
        if name in {START, END}:
            raise ValueError(f"Node name reserved: {name}")
        self._nodes[name] = fn
        return self

    def add_edge(self, source: str, target: str) -> StateGraph:
        if source in self._conditional:
            raise ValueError(f"{source} already has conditional edges")
        self._edges[source] = target
        return self

    def add_conditional_edges(
        self,
        source: str,
        condition: ConditionFn,
        path_map: Mapping[str, str],
    ) -> StateGraph:
        if source in self._edges:
            raise ValueError(f"{source} already has a fixed edge")
        self._conditional[source] = (condition, dict(path_map))
        return self

    def set_entry_point(self, name: str) -> StateGraph:
        if name not in self._nodes:
            raise ValueError(f"Unknown entry node: {name}")
        self._entry = name
        return self

    def compile(self, checkpointer: MemorySaver | None = None) -> CompiledStateGraph:
        if not self._nodes:
            raise ValueError("Graph has no nodes")
        entry = self._entry or next(iter(self._nodes))
        if entry not in self._nodes:
            raise ValueError(f"Entry point missing: {entry}")
        return CompiledStateGraph(
            nodes=dict(self._nodes),
            edges=dict(self._edges),
            conditional=dict(self._conditional),
            entry=entry,
            checkpointer=checkpointer,
        )


class CompiledStateGraph:
    def __init__(
        self,
        nodes: dict[str, NodeFn],
        edges: dict[str, str],
        conditional: dict[str, tuple[ConditionFn, dict[str, str]]],
        entry: str,
        checkpointer: MemorySaver | None = None,
    ) -> None:
        self._nodes = nodes
        self._edges = edges
        self._conditional = conditional
        self._entry = entry
        self._checkpointer = checkpointer

    def _next(self, name: str, state: dict[str, Any]) -> str:
        if name in self._conditional:
            cond, path_map = self._conditional[name]
            key = str(cond(state))
            if key not in path_map:
                raise KeyError(f"Condition returned {key!r} not in path_map {list(path_map)}")
            return path_map[key]
        if name in self._edges:
            return self._edges[name]
        return END

    def stream(
        self,
        initial: Mapping[str, Any] | None = None,
        *,
        config: Mapping[str, Any] | None = None,
        max_steps: int = 64,
    ) -> Iterator[dict[str, Any]]:
        config = dict(config or {})
        thread_id = str(config.get("thread_id") or config.get("configurable", {}).get("thread_id") or "default")

        state: dict[str, Any] = {}
        if self._checkpointer is not None:
            prior = self._checkpointer.get(thread_id)
            if prior:
                state = prior
        if initial:
            state = _merge(state, dict(initial))

        node = self._entry
        steps = 0
        while node and node != END and steps < max_steps:
            steps += 1
            if node not in self._nodes:
                raise KeyError(f"Unknown node: {node}")
            update = self._nodes[node](state)
            state = _merge(state, update if update is not None else {})
            state["__last_node__"] = node
            state["__step__"] = steps
            if self._checkpointer is not None:
                self._checkpointer.put(thread_id, state)
            yield deepcopy_state(state)
            node = self._next(node, state)

        state["__finished__"] = True
        if self._checkpointer is not None:
            self._checkpointer.put(thread_id, state)
        yield deepcopy_state(state)

    def invoke(
        self,
        initial: Mapping[str, Any] | None = None,
        *,
        config: Mapping[str, Any] | None = None,
        max_steps: int = 64,
    ) -> dict[str, Any]:
        last: dict[str, Any] = {}
        for snap in self.stream(initial, config=config, max_steps=max_steps):
            last = snap
        return last


def deepcopy_state(state: Mapping[str, Any]) -> dict[str, Any]:
    return deepcopy(dict(state))


# --- Convenience aliases (LangGraph naming familiarity) ---
StateGraphBuilder = StateGraph
