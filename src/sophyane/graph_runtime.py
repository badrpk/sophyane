"""Sophyane 21 deterministic and durable state-graph runtime.

The module stays dependency-free while providing the core orchestration features
expected from a modern agent graph: explicit state, nodes and edges, conditional
routing, cycles, retries, durable checkpoints, interrupts, resume, streaming,
telemetry and bounded parallel fan-out.
"""
from __future__ import annotations

import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from sophyane.config import DATA_DIR, ensure_directories

State = dict[str, Any]
Node = Callable[[State], Any]
Condition = Callable[[State], str]
Progress = Callable[[str], None]


class GraphError(RuntimeError):
    """Base graph definition or execution error."""


class GraphDefinitionError(GraphError):
    """Raised when a graph contains invalid nodes or routes."""


class RecursionLimitError(GraphError):
    """Raised when a graph exceeds its bounded execution limit."""


class GraphInterrupt(GraphError):
    """Raised at a configured human-in-the-loop interrupt boundary."""

    def __init__(self, node: str, checkpoint_id: str | None) -> None:
        super().__init__(f"graph interrupted before node {node}")
        self.node = node
        self.checkpoint_id = checkpoint_id


@dataclass(frozen=True)
class Command:
    """Atomic state update plus an optional dynamic destination."""

    update: State = field(default_factory=dict)
    goto: str = "END"


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    retry_exceptions: tuple[type[BaseException], ...] = (TimeoutError,)
    delay_seconds: float = 0.0
    backoff: float = 1.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.delay_seconds < 0:
            raise ValueError("delay_seconds cannot be negative")
        if self.backoff < 1:
            raise ValueError("backoff must be at least 1")


@dataclass(slots=True)
class GraphEvent:
    sequence: int
    node: str
    status: str
    elapsed_seconds: float
    attempt: int = 1
    detail: str = ""


@dataclass(slots=True)
class GraphResult:
    state: State
    trace: list[str]
    events: list[GraphEvent]
    completed: bool
    next_node: str
    checkpoint_id: str | None


class DurableStore:
    """SQLite/WAL-backed checkpoints, interrupts and named thread state."""

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
    """Builder and executable graph with LangGraph-style primitives."""

    START = "START"
    END = "END"

    def __init__(self, store: DurableStore | None = None) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, str] = {}
        self.conditions: dict[str, tuple[Condition, dict[str, str] | None]] = {}
        self.retries: dict[str, RetryPolicy] = {}
        self.store = store or DurableStore()
        self.interrupt_before: set[str] = set()

    def add_node(
        self,
        name: str,
        function: Node,
        retry_policy: RetryPolicy | None = None,
    ) -> "StateGraph":
        if not name or name in {self.START, self.END}:
            raise GraphDefinitionError(f"reserved or empty node name: {name!r}")
        if name in self.nodes:
            raise GraphDefinitionError(f"duplicate node: {name}")
        self.nodes[name] = function
        if retry_policy:
            self.retries[name] = retry_policy
        return self

    def add_edge(self, source: str, target: str) -> "StateGraph":
        if source in self.edges or source in self.conditions:
            raise GraphDefinitionError(f"outgoing route already configured: {source}")
        self.edges[source] = target
        return self

    def add_conditional_edges(
        self,
        source: str,
        selector: Condition,
        routes: Mapping[str, str] | None = None,
    ) -> "StateGraph":
        if source in self.edges or source in self.conditions:
            raise GraphDefinitionError(f"outgoing route already configured: {source}")
        self.conditions[source] = (selector, dict(routes) if routes is not None else None)
        return self

    def set_interrupt_before(self, *nodes: str) -> "StateGraph":
        self.interrupt_before.update(nodes)
        return self

    def compile(self) -> "StateGraph":
        """Validate and return this executable graph for builder compatibility."""

        if self.START not in self.edges:
            raise GraphDefinitionError("graph requires an edge from START")
        known = set(self.nodes) | {self.START, self.END}
        for source, target in self.edges.items():
            if source not in known or target not in known:
                raise GraphDefinitionError(f"unknown edge: {source} -> {target}")
        for source, (_, routes) in self.conditions.items():
            if source not in self.nodes:
                raise GraphDefinitionError(f"unknown conditional source: {source}")
            if routes:
                unknown = set(routes.values()) - known
                if unknown:
                    raise GraphDefinitionError(f"unknown conditional targets: {sorted(unknown)}")
        unknown_interrupts = self.interrupt_before - set(self.nodes)
        if unknown_interrupts:
            raise GraphDefinitionError(f"unknown interrupt nodes: {sorted(unknown_interrupts)}")
        return self

    @staticmethod
    def merge(base: State, update: State) -> State:
        """Shallow merge with last-write-wins.

        List values are replaced, not concatenated. Nodes that want to grow a
        list must return the full new list themselves (e.g. ``trace + [name]``).
        Automatic list-append was double-applying those updates and corrupting
        traces (e.g. ``['a','a','b',...]``).
        """
        merged = dict(base)
        for key, value in update.items():
            merged[key] = value
        return merged

    def _run_node(self, name: str, state: State) -> tuple[State | Command, int]:
        function = self.nodes[name]
        policy = self.retries.get(name, RetryPolicy(max_attempts=1, retry_exceptions=()))
        delay = policy.delay_seconds
        for attempt in range(1, policy.max_attempts + 1):
            try:
                return function(dict(state)), attempt
            except policy.retry_exceptions:
                if attempt >= policy.max_attempts:
                    raise
                if delay:
                    time.sleep(delay)
                    delay *= policy.backoff
        raise GraphError(f"node {name} exhausted retry policy")

    def _next_node(self, current: str, state: State, result: State | Command) -> tuple[State, str]:
        if isinstance(result, Command):
            return self.merge(state, result.update), result.goto
        merged = self.merge(state, result)
        if current in self.conditions:
            selector, routes = self.conditions[current]
            decision = selector(merged)
            if routes is not None:
                try:
                    return merged, routes[decision]
                except KeyError as error:
                    raise GraphError(
                        f"conditional node {current} returned unknown route {decision!r}"
                    ) from error
            return merged, decision
        return merged, self.edges.get(current, self.END)

    def invoke(
        self,
        initial_state: State,
        *,
        recursion_limit: int = 100,
        checkpoint_id: str | None = None,
        resume: bool = False,
        progress: Progress | None = None,
        ignore_interrupt_once: bool = False,
        return_result: bool = False,
    ) -> State | GraphResult:
        self.compile()
        report = progress or (lambda _message: None)
        state = dict(initial_state)
        current = self.edges[self.START]
        trace: list[str] = []
        events: list[GraphEvent] = []

        if checkpoint_id and resume:
            saved = self.store.get("checkpoint", checkpoint_id)
            if not saved:
                raise GraphError(f"checkpoint not found: {checkpoint_id}")
            state = dict(saved["state"])
            current = str(saved["next_node"])
            trace = list(saved.get("trace", []))
            events = [GraphEvent(**item) for item in saved.get("events", [])]

        executions = 0
        skip_interrupt = ignore_interrupt_once
        while current != self.END:
            if executions >= recursion_limit:
                raise RecursionLimitError(f"graph exceeded recursion limit {recursion_limit}")
            if current not in self.nodes:
                raise GraphError(f"unknown node: {current}")
            if current in self.interrupt_before and not skip_interrupt:
                self._checkpoint(checkpoint_id, state, current, trace, events)
                raise GraphInterrupt(current, checkpoint_id)
            skip_interrupt = False

            executions += 1
            report(f"Graph node {current}: started")
            started = time.monotonic()
            result, attempt = self._run_node(current, state)
            state, next_node = self._next_node(current, state, result)
            elapsed = time.monotonic() - started
            trace.append(current)
            events.append(
                GraphEvent(
                    sequence=len(events) + 1,
                    node=current,
                    status="completed",
                    elapsed_seconds=elapsed,
                    attempt=attempt,
                )
            )
            self._checkpoint(checkpoint_id, state, next_node, trace, events)
            report(f"Graph node {current}: completed in {elapsed:.3f}s -> {next_node}")
            current = next_node

        state.setdefault("trace", trace)
        result_object = GraphResult(
            state=state,
            trace=trace,
            events=events,
            completed=True,
            next_node=self.END,
            checkpoint_id=checkpoint_id,
        )
        return result_object if return_result else state

    def resume(
        self,
        checkpoint_id: str,
        *,
        recursion_limit: int = 100,
        progress: Progress | None = None,
        return_result: bool = False,
    ) -> State | GraphResult:
        return self.invoke(
            {},
            recursion_limit=recursion_limit,
            checkpoint_id=checkpoint_id,
            resume=True,
            progress=progress,
            ignore_interrupt_once=True,
            return_result=return_result,
        )

    def get_state(self, checkpoint_id: str) -> State | None:
        return self.store.get("checkpoint", checkpoint_id)

    def stream(
        self,
        initial_state: State,
        *,
        recursion_limit: int = 100,
        progress: Progress | None = None,
    ) -> Iterable[dict[str, Any]]:
        self.compile()
        report = progress or (lambda _message: None)
        state = dict(initial_state)
        current = self.edges[self.START]
        executions = 0
        while current != self.END:
            executions += 1
            if executions > recursion_limit:
                raise RecursionLimitError(f"graph exceeded recursion limit {recursion_limit}")
            started = time.monotonic()
            result, attempt = self._run_node(current, state)
            state, next_node = self._next_node(current, state, result)
            event = {
                "node": current,
                "status": "completed",
                "attempt": attempt,
                "elapsed_seconds": time.monotonic() - started,
                "next_node": next_node,
                "state": dict(state),
            }
            report(f"Graph node {current}: streamed -> {next_node}")
            yield event
            current = next_node

    def _checkpoint(
        self,
        checkpoint_id: str | None,
        state: State,
        next_node: str,
        trace: list[str],
        events: list[GraphEvent],
    ) -> None:
        if checkpoint_id:
            self.store.put(
                "checkpoint",
                checkpoint_id,
                {
                    "state": state,
                    "next_node": next_node,
                    "trace": trace,
                    "events": [asdict(event) for event in events],
                },
            )


def fan_out(
    values: Iterable[Any],
    worker: Callable[[Any], Any],
    *,
    max_workers: int = 1,
) -> list[Any]:
    """Map work deterministically, optionally using bounded parallel threads."""

    items = list(values)
    if max_workers <= 1 or len(items) <= 1:
        return [worker(value) for value in items]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(worker, items))


def _invoke_linear(nodes, edges, start, end, state):
    """Deterministic single-path invoke for fixed edge maps.

    edges: dict[str, str] direct edges; start/end are sentinel strings.
    """
    current = edges.get(start)
    seen_steps = 0
    max_steps = max(32, len(nodes) * 4)
    while current and current != end and seen_steps < max_steps:
        fn = nodes.get(current)
        if fn is None:
            break
        update = fn(state) or {}
        if isinstance(state, dict) and isinstance(update, dict):
            state = {**state, **update}
        else:
            state = update
        current = edges.get(current)
        seen_steps += 1
    return state
