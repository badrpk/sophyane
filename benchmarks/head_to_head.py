#!/usr/bin/env python3
"""Head-to-head deterministic runtime benchmark for Sophyane and LangGraph.

Both runtimes execute equivalent state graphs without LLM or network calls.
The benchmark measures correctness first, then warm latency, throughput and
Python allocation peaks. Results are written to JSON and Markdown.
"""
from __future__ import annotations

import gc
import importlib.metadata
import json
import os
import platform
import statistics
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any, Callable, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph as LangStateGraph

from sophyane.graph_runtime import DurableStore, RetryPolicy
from sophyane.graph_runtime import StateGraph as SophyaneStateGraph
from sophyane.version import __version__ as sophyane_version

ITERATIONS = int(os.environ.get("BENCH_ITERATIONS", "2000"))
WARMUP = int(os.environ.get("BENCH_WARMUP", "200"))
OUTPUT_DIR = Path(os.environ.get("BENCH_OUTPUT_DIR", "benchmark-results"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


class BenchState(TypedDict, total=False):
    value: int
    count: int
    route: str
    attempts: int
    trace: list[str]


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * p))))
    return ordered[index]


def measure(name: str, invoke: Callable[[], dict[str, Any]], validator: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    for _ in range(WARMUP):
        result = invoke()
        if not validator(result):
            raise AssertionError(f"{name} failed correctness during warmup: {result!r}")

    gc.collect()
    tracemalloc.start()
    latencies: list[float] = []
    started = time.perf_counter()
    last: dict[str, Any] = {}
    for _ in range(ITERATIONS):
        one = time.perf_counter_ns()
        last = invoke()
        latencies.append((time.perf_counter_ns() - one) / 1_000_000)
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    correct = validator(last)
    if not correct:
        raise AssertionError(f"{name} failed correctness after measurement: {last!r}")

    return {
        "correct": True,
        "iterations": ITERATIONS,
        "total_seconds": elapsed,
        "ops_per_second": ITERATIONS / elapsed,
        "latency_ms_mean": statistics.fmean(latencies),
        "latency_ms_median": statistics.median(latencies),
        "latency_ms_p95": percentile(latencies, 0.95),
        "latency_ms_p99": percentile(latencies, 0.99),
        "python_peak_bytes": peak,
        "last_result": last,
    }


def build_sophyane_linear() -> Callable[[], dict[str, Any]]:
    graph = SophyaneStateGraph()
    graph.add_node("load", lambda s: {"value": s.get("value", 0) + 2})
    graph.add_node("transform", lambda s: {"value": s["value"] * 5})
    graph.add_node("validate", lambda s: {"valid": s["value"] == 30})
    graph.add_edge(graph.START, "load")
    graph.add_edge("load", "transform")
    graph.add_edge("transform", "validate")
    graph.add_edge("validate", graph.END)
    return lambda: graph.invoke({"value": 4})


def build_langgraph_linear() -> Callable[[], dict[str, Any]]:
    graph = LangStateGraph(dict)
    graph.add_node("load", lambda s: {"value": s.get("value", 0) + 2})
    graph.add_node("transform", lambda s: {"value": s["value"] * 5})
    graph.add_node("validate", lambda s: {"valid": s["value"] == 30})
    graph.add_edge(START, "load")
    graph.add_edge("load", "transform")
    graph.add_edge("transform", "validate")
    graph.add_edge("validate", END)
    compiled = graph.compile()
    return lambda: compiled.invoke({"value": 4})


def build_sophyane_conditional() -> Callable[[], dict[str, Any]]:
    graph = SophyaneStateGraph()
    graph.add_node("classify", lambda s: {"route": "approved" if s["value"] >= 70 else "rejected"})
    graph.add_node("approved", lambda s: {"status": "approved"})
    graph.add_node("rejected", lambda s: {"status": "rejected"})
    graph.add_edge(graph.START, "classify")
    graph.add_conditional_edges("classify", lambda s: s["route"])
    graph.add_edge("approved", graph.END)
    graph.add_edge("rejected", graph.END)
    return lambda: graph.invoke({"value": 83})


def build_langgraph_conditional() -> Callable[[], dict[str, Any]]:
    graph = LangStateGraph(dict)
    graph.add_node("classify", lambda s: {"route": "approved" if s["value"] >= 70 else "rejected"})
    graph.add_node("approved", lambda s: {"status": "approved"})
    graph.add_node("rejected", lambda s: {"status": "rejected"})
    graph.add_edge(START, "classify")
    graph.add_conditional_edges("classify", lambda s: s["route"], ["approved", "rejected"])
    graph.add_edge("approved", END)
    graph.add_edge("rejected", END)
    compiled = graph.compile()
    return lambda: compiled.invoke({"value": 83})


def build_sophyane_loop() -> Callable[[], dict[str, Any]]:
    graph = SophyaneStateGraph()
    graph.add_node("increment", lambda s: {"count": s.get("count", 0) + 1})
    graph.add_edge(graph.START, "increment")
    graph.add_conditional_edges("increment", lambda s: "increment" if s["count"] < 10 else graph.END)
    return lambda: graph.invoke({"count": 0}, recursion_limit=20)


def build_langgraph_loop() -> Callable[[], dict[str, Any]]:
    graph = LangStateGraph(dict)
    graph.add_node("increment", lambda s: {"count": s.get("count", 0) + 1})
    graph.add_edge(START, "increment")
    graph.add_conditional_edges("increment", lambda s: "increment" if s["count"] < 10 else END, ["increment", END])
    compiled = graph.compile()
    return lambda: compiled.invoke({"count": 0}, config={"recursion_limit": 20})


def build_sophyane_retry() -> Callable[[], dict[str, Any]]:
    attempts = {"value": 0}
    def node(state: dict[str, Any]) -> dict[str, Any]:
        attempts["value"] += 1
        if attempts["value"] % 3 != 0:
            raise TimeoutError("simulated")
        return {"attempts": 3, "status": "success"}
    graph = SophyaneStateGraph()
    graph.add_node("retry", node, RetryPolicy(max_attempts=3, retry_exceptions=(TimeoutError,)))
    graph.add_edge(graph.START, "retry")
    graph.add_edge("retry", graph.END)
    return lambda: graph.invoke({})


def build_langgraph_retry() -> Callable[[], dict[str, Any]]:
    attempts = {"value": 0}
    def node(state: dict[str, Any]) -> dict[str, Any]:
        attempts["value"] += 1
        if attempts["value"] % 3 != 0:
            raise TimeoutError("simulated")
        return {"attempts": 3, "status": "success"}
    graph = LangStateGraph(dict)
    graph.add_node("retry", node, retry_policy={"max_attempts": 3, "retry_on": TimeoutError, "initial_interval": 0.0, "backoff_factor": 1.0, "max_interval": 0.0, "jitter": False})
    graph.add_edge(START, "retry")
    graph.add_edge("retry", END)
    compiled = graph.compile()
    return lambda: compiled.invoke({})


def persistence_correctness() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        store = DurableStore(Path(tmp) / "sophyane.db")
        sg = SophyaneStateGraph(store)
        sg.add_node("a", lambda s: {"value": s.get("value", 0) + 1})
        sg.add_node("b", lambda s: {"value": s["value"] * 2})
        sg.add_edge(sg.START, "a")
        sg.add_edge("a", "b")
        sg.add_edge("b", sg.END)
        first = sg.invoke({"value": 3}, checkpoint_id="same")
        saved = store.get("checkpoint", "same")

        saver = InMemorySaver()
        lg = LangStateGraph(dict)
        lg.add_node("a", lambda s: {"value": s.get("value", 0) + 1})
        lg.add_node("b", lambda s: {"value": s["value"] * 2})
        lg.add_edge(START, "a")
        lg.add_edge("a", "b")
        lg.add_edge("b", END)
        compiled = lg.compile(checkpointer=saver)
        config = {"configurable": {"thread_id": "same"}}
        second = compiled.invoke({"value": 3}, config=config)
        snapshot = compiled.get_state(config)

        return {
            "sophyane": {"correct": first["value"] == 8 and saved is not None},
            "langgraph": {"correct": second["value"] == 8 and snapshot.values["value"] == 8},
        }


def main() -> int:
    suites = {
        "linear_3_node": (
            build_sophyane_linear(), build_langgraph_linear(),
            lambda r: r.get("value") == 30 and r.get("valid") is True,
        ),
        "conditional_route": (
            build_sophyane_conditional(), build_langgraph_conditional(),
            lambda r: r.get("route") == "approved" and r.get("status") == "approved",
        ),
        "loop_10_steps": (
            build_sophyane_loop(), build_langgraph_loop(),
            lambda r: r.get("count") == 10,
        ),
        "retry_two_failures": (
            build_sophyane_retry(), build_langgraph_retry(),
            lambda r: r.get("attempts") == 3 and r.get("status") == "success",
        ),
    }

    results: dict[str, Any] = {
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "iterations": ITERATIONS,
            "warmup": WARMUP,
            "sophyane_version": sophyane_version,
            "langgraph_version": importlib.metadata.version("langgraph"),
        },
        "tasks": {},
        "persistence": persistence_correctness(),
    }

    for task, (sophyane_invoke, langgraph_invoke, validator) in suites.items():
        results["tasks"][task] = {
            "sophyane": measure(f"Sophyane/{task}", sophyane_invoke, validator),
            "langgraph": measure(f"LangGraph/{task}", langgraph_invoke, validator),
        }

    wins = {"sophyane": 0, "langgraph": 0, "ties": 0}
    for task, task_results in results["tasks"].items():
        s = task_results["sophyane"]["latency_ms_median"]
        l = task_results["langgraph"]["latency_ms_median"]
        if abs(s - l) <= max(s, l) * 0.02:
            wins["ties"] += 1
        elif s < l:
            wins["sophyane"] += 1
        else:
            wins["langgraph"] += 1
    results["median_latency_wins"] = wins

    json_path = OUTPUT_DIR / "head-to-head.json"
    json_path.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# Sophyane vs LangGraph Head-to-Head",
        "",
        f"- Sophyane: `{sophyane_version}`",
        f"- LangGraph: `{results['environment']['langgraph_version']}`",
        f"- Python: `{results['environment']['python']}`",
        f"- Warmup: `{WARMUP}` invocations per task",
        f"- Measured: `{ITERATIONS}` invocations per task",
        "",
        "| Task | Runtime | Correct | Median ms | P95 ms | Ops/s | Peak Python bytes |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for task, task_results in results["tasks"].items():
        for runtime in ("sophyane", "langgraph"):
            row = task_results[runtime]
            lines.append(
                f"| {task} | {runtime} | {row['correct']} | "
                f"{row['latency_ms_median']:.6f} | {row['latency_ms_p95']:.6f} | "
                f"{row['ops_per_second']:.2f} | {row['python_peak_bytes']} |"
            )
    lines.extend([
        "",
        "## Persistence correctness",
        "",
        f"- Sophyane: `{results['persistence']['sophyane']['correct']}`",
        f"- LangGraph: `{results['persistence']['langgraph']['correct']}`",
        "",
        "## Median-latency wins",
        "",
        f"- Sophyane: **{wins['sophyane']}**",
        f"- LangGraph: **{wins['langgraph']}**",
        f"- Ties (within 2%): **{wins['ties']}**",
        "",
        "## Scope",
        "",
        "This benchmark compares deterministic local graph-runtime overhead. It does not compare ecosystem maturity, distributed deployment, observability products, integrations, or LLM quality.",
    ])
    md_path = OUTPUT_DIR / "head-to-head.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(md_path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
