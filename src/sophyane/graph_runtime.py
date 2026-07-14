"""Deterministic, durable state-graph primitives used by Sophyane v12."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from sophyane.config import DATA_DIR, ensure_directories

State = dict[str, Any]
Node = Callable[[State], State]
Condition = Callable[[State], str]


class GraphError(RuntimeError):
    """Base graph execution error."""


class RecursionLimitError(GraphError):
    """Raised when a graph exceeds its bounded execution limit."""


@dataclass(frozen=True)
class Command:
    """Atomic state update plus dynamic destination."""

    update: State = field(default_factory=dict)
    goto: str = "END"


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    retry_exceptions: tuple[type[BaseException], ...] = (TimeoutError,)
    delay_seconds: float = 0.0


class DurableStore:
    """SQLite-backed checkpoints, interrupts, and named thread state."""

    def __init__(self, path: Path | None = None) -> None:
        ensure_directories()
        self.path = Path(path or (DATA_DIR / "graphs.db"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS graph_state (
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(namespace, key)
                )
                """
            )
            connection.commit()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=15000")
        return connection

    def put(self, namespace: str, key: str, payload: State) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO graph_state(namespace, key, payload, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(namespace, key) DO UPDATE SET
                    payload=excluded.payload,
                    updated_at=excluded.updated_at
                """,
                (namespace, key, encoded, time.time()),
            )
            connection.commit()

    def get(self, namespace: str, key: str) -> State | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM graph_state WHERE namespace=? AND key=?",
                (namespace, key),
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def delete(self, namespace: str, key: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM graph_state WHERE namespace=? AND key=?",
                (namespace, key),
            )
            connection.commit()
            return bool(cursor.rowcount)


class StateGraph:
    """Small deterministic graph runtime with routing, retries and checkpoints."""

    START = "START"
    END = "END"

    def __init__(self, store: DurableStore | None = None) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, str] = {}
        self.conditions: dict[str, Condition] = {}
        self.retries: dict[str, RetryPolicy] = {}
        self.store = store or DurableStore()

    def add_node(
        self,
        name: str,
        function: Node,
        retry_policy: RetryPolicy | None = None,
    ) -> "StateGraph":
        if name in {self.START, self.END}:
            raise ValueError(f"reserved node name: {name}")
        self.nodes[name] = function
        if retry_policy:
            self.retries[name] = retry_policy
        return self

    def add_edge(self, source: str, target: str) -> "StateGraph":
        self.edges[source] = target
        return self

    def add_conditional_edges(
        self,
        source: str,
        selector: Condition,
    ) -> "StateGraph":
        self.conditions[source] = selector
        return self

    @staticmethod
    def merge(base: State, update: State) -> State:
        merged = dict(base)
        for key, value in update.items():
            previous = merged.get(key)
            if isinstance(previous, list) and isinstance(value, list):
                merged[key] = [*previous, *value]
            elif isinstance(previous, (int, float)) and isinstance(value, (int, float)):
                merged[key] = value
            else:
                merged[key] = value
        return merged

    def _run_node(self, name: str, state: State) -> State | Command:
        function = self.nodes[name]
        policy = self.retries.get(name, RetryPolicy(max_attempts=1, retry_exceptions=()))
        attempts = 0
        while True:
            attempts += 1
            try:
                return function(dict(state))
            except policy.retry_exceptions:
                if attempts >= policy.max_attempts:
                    raise
                if policy.delay_seconds:
                    time.sleep(policy.delay_seconds)

    def invoke(
        self,
        initial_state: State,
        *,
        recursion_limit: int = 100,
        checkpoint_id: str | None = None,
        resume: bool = False,
    ) -> State:
        state = dict(initial_state)
        current = self.edges.get(self.START, self.END)
        trace: list[str] = []

        if checkpoint_id and resume:
            saved = self.store.get("checkpoint", checkpoint_id)
            if saved:
                state = dict(saved["state"])
                current = str(saved["next_node"])
                trace = list(saved.get("trace", []))

        executions = 0
        while current != self.END:
            executions += 1
            if executions > recursion_limit:
                raise RecursionLimitError(
                    f"graph exceeded recursion limit {recursion_limit}"
                )
            if current not in self.nodes:
                raise GraphError(f"unknown node: {current}")

            result = self._run_node(current, state)
            trace.append(current)

            if isinstance(result, Command):
                state = self.merge(state, result.update)
                next_node = result.goto
            else:
                state = self.merge(state, result)
                if current in self.conditions:
                    next_node = self.conditions[current](state)
                else:
                    next_node = self.edges.get(current, self.END)

            if checkpoint_id:
                self.store.put(
                    "checkpoint",
                    checkpoint_id,
                    {"state": state, "next_node": next_node, "trace": trace},
                )
            current = next_node

        state.setdefault("trace", trace)
        return state

    def stream(
        self,
        initial_state: State,
        *,
        recursion_limit: int = 100,
    ) -> Iterable[dict[str, Any]]:
        state = dict(initial_state)
        current = self.edges.get(self.START, self.END)
        executions = 0
        while current != self.END:
            executions += 1
            if executions > recursion_limit:
                raise RecursionLimitError(
                    f"graph exceeded recursion limit {recursion_limit}"
                )
            result = self._run_node(current, state)
            if isinstance(result, Command):
                state = self.merge(state, result.update)
                next_node = result.goto
            else:
                state = self.merge(state, result)
                next_node = (
                    self.conditions[current](state)
                    if current in self.conditions
                    else self.edges.get(current, self.END)
                )
            yield {"node": current, "status": "completed", "state": dict(state)}
            current = next_node


def fan_out(values: Iterable[Any], worker: Callable[[Any], Any]) -> list[Any]:
    """Deterministic map helper preserving input order."""

    return [worker(value) for value in values]
