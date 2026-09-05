"""Bounded execution for already-structured read-only task graphs.

This module is intentionally an execution primitive, not an intent planner.
Callers must supply validated nodes and explicit read-only worker callables.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
import time
from typing import Any, Callable, Iterable

MAX_GRAPH_NODES = 32
MAX_WORKERS = 8


@dataclass(frozen=True)
class ReadonlyGraphNode:
    node_id: str
    worker: Callable[[], Any]
    depends_on: tuple[str, ...] = ()
    read_only: bool = True
    cancel: Callable[[], None] | None = None


def _validate_nodes(nodes: Iterable[ReadonlyGraphNode]) -> dict[str, ReadonlyGraphNode]:
    ordered = list(nodes)
    if not ordered or len(ordered) > MAX_GRAPH_NODES:
        raise ValueError("graph must contain 1-32 nodes")
    result: dict[str, ReadonlyGraphNode] = {}
    for node in ordered:
        if (
            not isinstance(node.node_id, str)
            or not node.node_id
            or node.node_id in result
            or not callable(node.worker)
            or node.read_only is not True
            or (node.cancel is not None and not callable(node.cancel))
        ):
            raise ValueError("invalid read-only graph node")
        result[node.node_id] = node
    for node in result.values():
        if node.node_id in node.depends_on or any(dep not in result for dep in node.depends_on):
            raise ValueError("graph contains an invalid dependency")
    return result


def _validate_result(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("ok"), bool):
        return {"ok": False, "error": "worker returned no structured result"}
    return dict(value)


def _signal_cancel(node: ReadonlyGraphNode) -> None:
    """Best-effort cooperative cancellation; never claim hard termination."""
    if node.cancel is None:
        return
    try:
        node.cancel()
    except Exception:
        pass


def execute_readonly_task_graph(
    nodes: Iterable[ReadonlyGraphNode],
    *,
    max_workers: int = 4,
    deadline_seconds: float = 30.0,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Execute independent read-only nodes in parallel and aggregate safely."""
    graph = _validate_nodes(nodes)
    if not isinstance(max_workers, int) or isinstance(max_workers, bool) or not 1 <= max_workers <= MAX_WORKERS:
        raise ValueError("max_workers must be between 1 and 8")
    if deadline_seconds <= 0 or deadline_seconds != deadline_seconds or deadline_seconds == float("inf"):
        raise ValueError("deadline_seconds must be finite and positive")

    started = clock()
    deadline = started + deadline_seconds
    results: dict[str, dict[str, Any]] = {}
    pending = set(graph)
    executor = ThreadPoolExecutor(max_workers=min(max_workers, len(graph)))
    try:
        while pending:
            if clock() >= deadline:
                for node_id in sorted(pending):
                    results[node_id] = {"ok": False, "error": "graph deadline exceeded", "skipped": True}
                break
            ready = sorted(
                node_id
                for node_id in pending
                if all(dep in results for dep in graph[node_id].depends_on)
            )
            if not ready:
                for node_id in sorted(pending):
                    results[node_id] = {"ok": False, "error": "graph dependency cycle", "skipped": True}
                break
            blocked = [
                node_id for node_id in ready
                if any(not results[dep].get("ok", False) for dep in graph[node_id].depends_on)
            ]
            for node_id in blocked:
                results[node_id] = {"ok": False, "error": "dependency failed", "skipped": True}
                pending.remove(node_id)
            runnable = [node_id for node_id in ready if node_id not in blocked]
            if runnable:
                futures = {node_id: executor.submit(graph[node_id].worker) for node_id in runnable}
                for node_id in runnable:
                    remaining = deadline - clock()
                    if remaining <= 0:
                        _signal_cancel(graph[node_id])
                        results[node_id] = {"ok": False, "error": "graph deadline exceeded"}
                        continue
                    try:
                        results[node_id] = _validate_result(
                            futures[node_id].result(timeout=remaining)
                        )
                    except FutureTimeout:
                        _signal_cancel(graph[node_id])
                        results[node_id] = {"ok": False, "error": "graph deadline exceeded"}
                    except Exception as exc:
                        results[node_id] = {"ok": False, "error": type(exc).__name__}
                pending.difference_update(runnable)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    ordered_results = [
        {"node_id": node_id, **results[node_id]}
        for node_id in sorted(results)
    ]
    return {
        "ok": bool(ordered_results) and all(item.get("ok") is True for item in ordered_results),
        "nodes": ordered_results,
        "completed": sum(item.get("ok") is True for item in ordered_results),
        "total": len(graph),
        "elapsed_seconds": max(0.0, clock() - started),
    }


__all__ = ["ReadonlyGraphNode", "execute_readonly_task_graph"]
