#!/usr/bin/env python3
"""
Sophyane versus LangGraph on five local/native tasks.

Fairness rules
--------------
1. Both systems use the same installed NIFDU and Neuron executables.
2. No cloud LLM is called by the LangGraph baseline.
3. Sophyane uses its real try_any_native_reply() integration.
4. Each execution has a timeout.
5. Results report latency, success, output size and validation markers.
6. Benchmark claims are based only on measurements from this run.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph


ROOT = Path(__file__).resolve().parents[1]
RESULT_DIR = ROOT / "runtime" / "benchmarks"
TIMEOUT_SECONDS = int(os.environ.get("BENCH_TIMEOUT_SECONDS", "180"))
REPEATS = max(1, int(os.environ.get("BENCH_REPEATS", "1")))


def executable(path: str | Path | None) -> str | None:
    if not path:
        return None

    candidate = Path(path).expanduser()
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate.resolve())

    located = shutil.which(str(path))
    return str(Path(located).resolve()) if located else None


def detect_nifdu() -> str | None:
    candidates = [
        os.environ.get("SOPHYANE_NIFDU_BIN"),
        Path.home() / ".local" / "bin" / "nifdu",
        Path.home() / "nifdu" / "build" / "nifdu",
        "/tmp/nifdu-clean-build/nifdu",
    ]

    for candidate in candidates:
        found = executable(candidate)
        if found:
            return found

    return executable("nifdu")


def detect_neuron() -> str | None:
    candidates = [
        os.environ.get("SOPHYANE_NEURON_BIN"),
        Path.home() / "neuron_repo" / "build" / "test_neuron_capabilities",
        Path.home() / "nifdu" / "build" / "test_neuron_capabilities",
        "/tmp/nifdu-clean-build/test_neuron_capabilities",
    ]

    for candidate in candidates:
        found = executable(candidate)
        if found:
            return found

    return executable("test_neuron_capabilities")


NIFDU_BIN = detect_nifdu()
NEURON_BIN = detect_neuron()


@dataclass(frozen=True)
class Task:
    task_id: str
    name: str
    prompt: str
    expected_any: tuple[str, ...]
    use_nifdu: bool
    use_neuron: bool
    operation: str


TASKS = [
    Task(
        task_id="T1",
        name="Native worker discovery",
        prompt="show native workers status and check whether nifdu and neuron are available",
        expected_any=("nifdu", "neuron", "available", "ok"),
        use_nifdu=True,
        use_neuron=True,
        operation="status",
    ),
    Task(
        task_id="T2",
        name="Neuron capability audit",
        prompt="use neuron — run neuron capabilities benchmark",
        expected_any=("6/6", "passed", "capability", "neuron"),
        use_nifdu=False,
        use_neuron=True,
        operation="benchmark",
    ),
    Task(
        task_id="T3",
        name="NIFDU executable inspection",
        prompt="use nifdu native worker to inspect nifdu executable status and path",
        expected_any=("nifdu", "available", "path", "executable"),
        use_nifdu=True,
        use_neuron=False,
        operation="inspect",
    ),
    Task(
        task_id="T4",
        name="Combined throughput and latency",
        prompt="use nifdu and neuron to benchmark native throughput and latency",
        expected_any=("throughput", "latency", "faster", "nifdu", "neuron"),
        use_nifdu=True,
        use_neuron=True,
        operation="benchmark",
    ),
    Task(
        task_id="T5",
        name="Spiking efficiency verification",
        prompt=(
            "use neuron native worker to verify spiking memory, energy and "
            "multi-user concurrency capabilities"
        ),
        expected_any=("memory", "energy", "concurrency", "passed", "neuron"),
        use_nifdu=False,
        use_neuron=True,
        operation="benchmark",
    ),
]


@dataclass
class RunResult:
    system: str
    task_id: str
    task_name: str
    repeat: int
    ok: bool
    validated: bool
    elapsed_ms: float
    output_bytes: int
    estimated_llm_tokens: int
    worker_selection: str
    output: str
    error: str | None = None


def validate_output(text: str, expected_any: tuple[str, ...]) -> bool:
    normalized = text.casefold()
    return any(marker.casefold() in normalized for marker in expected_any)


def run_process(command: list[str], timeout: int = TIMEOUT_SECONDS) -> dict[str, Any]:
    started = time.perf_counter()

    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        combined = "\n".join(
            part for part in (completed.stdout, completed.stderr) if part
        ).strip()

        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "elapsed_ms": elapsed_ms,
            "output": combined,
            "error": None if completed.returncode == 0 else (
                f"process returned {completed.returncode}"
            ),
        }

    except subprocess.TimeoutExpired as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""

        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")

        return {
            "ok": False,
            "returncode": None,
            "elapsed_ms": elapsed_ms,
            "output": f"{stdout}\n{stderr}".strip(),
            "error": f"timeout after {timeout} seconds",
        }

    except Exception as exc:
        return {
            "ok": False,
            "returncode": None,
            "elapsed_ms": (time.perf_counter() - started) * 1000.0,
            "output": "",
            "error": f"{type(exc).__name__}: {exc}",
        }


# ===========================================================================
# Sophyane runner
# ===========================================================================

def run_sophyane(task: Task, repeat: int) -> RunResult:
    started = time.perf_counter()
    output = ""
    error: str | None = None
    ok = False

    try:
        from sophyane.native_capability import try_any_native_reply

        reply = try_any_native_reply(task.prompt)
        output = "" if reply is None else str(reply)

        ok = reply is not None and bool(output.strip())
        if reply is None:
            error = "Sophyane native hook did not claim this task"

    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        output = traceback.format_exc()

    elapsed_ms = (time.perf_counter() - started) * 1000.0

    return RunResult(
        system="Sophyane",
        task_id=task.task_id,
        task_name=task.name,
        repeat=repeat,
        ok=ok,
        validated=ok and validate_output(output, task.expected_any),
        elapsed_ms=elapsed_ms,
        output_bytes=len(output.encode("utf-8", errors="replace")),
        estimated_llm_tokens=0 if ok else -1,
        worker_selection=(
            ("NIFDU+" if task.use_nifdu else "")
            + ("Neuron" if task.use_neuron else "")
        ).rstrip("+"),
        output=output,
        error=error,
    )


# ===========================================================================
# LangGraph runner
# ===========================================================================

class GraphState(TypedDict, total=False):
    task: Task
    nifdu_result: dict[str, Any]
    neuron_result: dict[str, Any]
    final_output: str
    ok: bool
    workers: list[str]


def graph_route(state: GraphState) -> GraphState:
    task = state["task"]
    workers: list[str] = []

    if task.use_nifdu:
        workers.append("nifdu")
    if task.use_neuron:
        workers.append("neuron")

    return {"workers": workers}


def nifdu_worker(task: Task) -> dict[str, Any]:
    started = time.perf_counter()

    if not NIFDU_BIN:
        return {
            "worker": "nifdu",
            "ok": False,
            "elapsed_ms": (time.perf_counter() - started) * 1000.0,
            "output": "NIFDU executable unavailable",
            "error": "NIFDU executable unavailable",
        }

    path = Path(NIFDU_BIN)
    stat = path.stat()

    # Inspection avoids launching an unknown long-running default server command.
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    output = json.dumps(
        {
            "worker": "nifdu",
            "available": True,
            "path": str(path),
            "executable": os.access(path, os.X_OK),
            "size_bytes": stat.st_size,
            "sha256": digest,
            "operation": task.operation,
        },
        indent=2,
        sort_keys=True,
    )

    return {
        "worker": "nifdu",
        "ok": True,
        "elapsed_ms": (time.perf_counter() - started) * 1000.0,
        "output": output,
        "error": None,
    }


def neuron_worker(task: Task) -> dict[str, Any]:
    if not NEURON_BIN:
        return {
            "worker": "neuron",
            "ok": False,
            "elapsed_ms": 0.0,
            "output": "Neuron capability executable unavailable",
            "error": "Neuron capability executable unavailable",
        }

    if task.operation == "status":
        path = Path(NEURON_BIN)
        return {
            "worker": "neuron",
            "ok": True,
            "elapsed_ms": 0.0,
            "output": json.dumps(
                {
                    "worker": "neuron",
                    "available": True,
                    "path": str(path),
                    "executable": os.access(path, os.X_OK),
                },
                indent=2,
            ),
            "error": None,
        }

    result = run_process([NEURON_BIN])
    result["worker"] = "neuron"
    return result


def execute_workers(state: GraphState) -> GraphState:
    task = state["task"]
    workers = state.get("workers", [])

    results: dict[str, dict[str, Any]] = {}

    # Run independent local workers concurrently.
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max(1, len(workers))
    ) as pool:
        futures: dict[concurrent.futures.Future[dict[str, Any]], str] = {}

        if "nifdu" in workers:
            futures[pool.submit(nifdu_worker, task)] = "nifdu"

        if "neuron" in workers:
            futures[pool.submit(neuron_worker, task)] = "neuron"

        for future, worker in futures.items():
            try:
                results[worker] = future.result(timeout=TIMEOUT_SECONDS + 5)
            except Exception as exc:
                results[worker] = {
                    "worker": worker,
                    "ok": False,
                    "elapsed_ms": 0.0,
                    "output": "",
                    "error": f"{type(exc).__name__}: {exc}",
                }

    update: GraphState = {}
    if "nifdu" in results:
        update["nifdu_result"] = results["nifdu"]
    if "neuron" in results:
        update["neuron_result"] = results["neuron"]

    return update


def merge_results(state: GraphState) -> GraphState:
    sections: list[str] = []
    statuses: list[bool] = []

    for key in ("nifdu_result", "neuron_result"):
        result = state.get(key)
        if not result:
            continue

        statuses.append(bool(result.get("ok")))
        worker = str(result.get("worker", key))
        output = str(result.get("output", "")).strip()
        error = result.get("error")

        section = [
            f"[{worker.upper()}]",
            output or "(no output)",
        ]

        if error:
            section.append(f"ERROR: {error}")

        sections.append("\n".join(section))

    return {
        "final_output": "\n\n".join(sections),
        "ok": bool(statuses) and all(statuses),
    }


def make_graph():
    graph = StateGraph(GraphState)
    graph.add_node("route", graph_route)
    graph.add_node("workers", execute_workers)
    graph.add_node("merge", merge_results)

    graph.add_edge(START, "route")
    graph.add_edge("route", "workers")
    graph.add_edge("workers", "merge")
    graph.add_edge("merge", END)

    return graph.compile()


LANGGRAPH_APP = make_graph()


def run_langgraph(task: Task, repeat: int) -> RunResult:
    started = time.perf_counter()
    error: str | None = None
    output = ""
    ok = False

    try:
        state = LANGGRAPH_APP.invoke({"task": task})
        output = str(state.get("final_output", ""))
        ok = bool(state.get("ok", False))

    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        output = traceback.format_exc()

    elapsed_ms = (time.perf_counter() - started) * 1000.0

    return RunResult(
        system="LangGraph",
        task_id=task.task_id,
        task_name=task.name,
        repeat=repeat,
        ok=ok,
        validated=ok and validate_output(output, task.expected_any),
        elapsed_ms=elapsed_ms,
        output_bytes=len(output.encode("utf-8", errors="replace")),
        estimated_llm_tokens=0,
        worker_selection=(
            ("NIFDU+" if task.use_nifdu else "")
            + ("Neuron" if task.use_neuron else "")
        ).rstrip("+"),
        output=output,
        error=error,
    )


def median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def summarize(results: list[RunResult]) -> dict[str, Any]:
    systems: dict[str, Any] = {}

    for system in ("Sophyane", "LangGraph"):
        subset = [result for result in results if result.system == system]
        latencies = [result.elapsed_ms for result in subset]

        systems[system] = {
            "runs": len(subset),
            "successful": sum(result.ok for result in subset),
            "validated": sum(result.validated for result in subset),
            "success_rate_percent": round(
                100.0 * sum(result.ok for result in subset) / len(subset), 2
            ) if subset else 0.0,
            "validation_rate_percent": round(
                100.0 * sum(result.validated for result in subset) / len(subset), 2
            ) if subset else 0.0,
            "total_elapsed_ms": round(sum(latencies), 3),
            "mean_elapsed_ms": round(
                statistics.fmean(latencies), 3
            ) if latencies else 0.0,
            "median_elapsed_ms": round(median(latencies), 3),
            "total_output_bytes": sum(result.output_bytes for result in subset),
            "estimated_llm_tokens": sum(
                max(0, result.estimated_llm_tokens) for result in subset
            ),
        }

    return systems


def markdown_report(
    results: list[RunResult],
    summary: dict[str, Any],
    generated_at: str,
) -> str:
    lines = [
        "# Sophyane vs LangGraph: five-task native benchmark",
        "",
        f"Generated: `{generated_at}`",
        "",
        "## Environment",
        "",
        f"- Python: `{sys.version.split()[0]}`",
        f"- NIFDU: `{NIFDU_BIN or 'not found'}`",
        f"- Neuron: `{NEURON_BIN or 'not found'}`",
        f"- Repeats per task: `{REPEATS}`",
        f"- Timeout: `{TIMEOUT_SECONDS} seconds`",
        "",
        "## Per-run results",
        "",
        "| Task | System | Run | Success | Validated | Time ms | Output bytes |",
        "|---|---|---:|:---:|:---:|---:|---:|",
    ]

    for result in results:
        lines.append(
            f"| {result.task_id}: {result.task_name} "
            f"| {result.system} "
            f"| {result.repeat} "
            f"| {'PASS' if result.ok else 'FAIL'} "
            f"| {'PASS' if result.validated else 'FAIL'} "
            f"| {result.elapsed_ms:.3f} "
            f"| {result.output_bytes} |"
        )

    lines.extend(
        [
            "",
            "## Aggregate results",
            "",
            "| System | Success | Validation | Mean ms | Median ms | Total ms | LLM tokens |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )

    for system, data in summary.items():
        lines.append(
            f"| {system} "
            f"| {data['successful']}/{data['runs']} "
            f"| {data['validated']}/{data['runs']} "
            f"| {data['mean_elapsed_ms']:.3f} "
            f"| {data['median_elapsed_ms']:.3f} "
            f"| {data['total_elapsed_ms']:.3f} "
            f"| {data['estimated_llm_tokens']} |"
        )

    s = summary["Sophyane"]
    l = summary["LangGraph"]

    lines.extend(["", "## Measured conclusion", ""])

    if s["validation_rate_percent"] != l["validation_rate_percent"]:
        winner = (
            "Sophyane"
            if s["validation_rate_percent"] > l["validation_rate_percent"]
            else "LangGraph"
        )
        lines.append(
            f"- **Validation winner:** {winner} "
            f"({s['validation_rate_percent']}% vs "
            f"{l['validation_rate_percent']}%)."
        )
    else:
        lines.append(
            f"- **Validation:** tied at "
            f"{s['validation_rate_percent']}%."
        )

    if s["median_elapsed_ms"] and l["median_elapsed_ms"]:
        latency_winner = (
            "Sophyane"
            if s["median_elapsed_ms"] < l["median_elapsed_ms"]
            else "LangGraph"
        )

        slower = max(s["median_elapsed_ms"], l["median_elapsed_ms"])
        faster = min(s["median_elapsed_ms"], l["median_elapsed_ms"])
        ratio = slower / faster if faster > 0 else 0.0

        lines.append(
            f"- **Median-latency winner:** {latency_winner}; "
            f"measured ratio `{ratio:.2f}x`."
        )

    lines.extend(
        [
            "- Both paths use local execution and therefore request zero "
            "cloud-LLM tokens in this benchmark.",
            "- The Neuron benchmark's internal performance claims are reported "
            "by its executable; this harness independently measures only "
            "end-to-end wall-clock time and validation.",
            "",
            "## Errors",
            "",
        ]
    )

    errors = [result for result in results if result.error]
    if not errors:
        lines.append("No harness errors were recorded.")
    else:
        for result in errors:
            lines.append(
                f"- `{result.system} {result.task_id} run "
                f"{result.repeat}`: {result.error}"
            )

    return "\n".join(lines) + "\n"


def main() -> int:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    print("=" * 72)
    print("Sophyane vs LangGraph — five-task native benchmark")
    print("=" * 72)
    print(f"NIFDU : {NIFDU_BIN or 'NOT FOUND'}")
    print(f"Neuron: {NEURON_BIN or 'NOT FOUND'}")
    print(f"Repeats: {REPEATS}")
    print()

    results: list[RunResult] = []

    for repeat in range(1, REPEATS + 1):
        for task in TASKS:
            print(
                f"[{task.task_id}] {task.name} "
                f"(repeat {repeat}/{REPEATS})"
            )

            sophyane_result = run_sophyane(task, repeat)
            results.append(sophyane_result)
            print(
                "  Sophyane : "
                f"{'PASS' if sophyane_result.ok else 'FAIL'} | "
                f"validated={'yes' if sophyane_result.validated else 'no'} | "
                f"{sophyane_result.elapsed_ms:.3f} ms"
            )

            langgraph_result = run_langgraph(task, repeat)
            results.append(langgraph_result)
            print(
                "  LangGraph: "
                f"{'PASS' if langgraph_result.ok else 'FAIL'} | "
                f"validated={'yes' if langgraph_result.validated else 'no'} | "
                f"{langgraph_result.elapsed_ms:.3f} ms"
            )
            print()

    summary = summarize(results)

    payload = {
        "generated_at": generated_at,
        "configuration": {
            "root": str(ROOT),
            "nifdu_binary": NIFDU_BIN,
            "neuron_binary": NEURON_BIN,
            "timeout_seconds": TIMEOUT_SECONDS,
            "repeats": REPEATS,
            "cloud_llm_used": False,
        },
        "tasks": [asdict(task) for task in TASKS],
        "results": [asdict(result) for result in results],
        "summary": summary,
    }

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    json_path = RESULT_DIR / f"sophyane-vs-langgraph-5-{stamp}.json"
    markdown_path = RESULT_DIR / f"sophyane-vs-langgraph-5-{stamp}.md"

    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    markdown_path.write_text(
        markdown_report(results, summary, generated_at),
        encoding="utf-8",
    )

    latest_json = RESULT_DIR / "sophyane-vs-langgraph-5-latest.json"
    latest_md = RESULT_DIR / "sophyane-vs-langgraph-5-latest.md"

    latest_json.write_text(
        json_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    latest_md.write_text(
        markdown_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    print("=" * 72)
    print("AGGREGATE")
    print("=" * 72)

    for system, data in summary.items():
        print(
            f"{system:10} "
            f"success={data['successful']}/{data['runs']} "
            f"validated={data['validated']}/{data['runs']} "
            f"mean={data['mean_elapsed_ms']:.3f}ms "
            f"median={data['median_elapsed_ms']:.3f}ms "
            f"tokens={data['estimated_llm_tokens']}"
        )

    print()
    print(f"JSON report    : {json_path}")
    print(f"Markdown report: {markdown_path}")
    print(f"Latest report  : {latest_md}")

    # Fail only when either framework has execution failures.
    all_ok = all(result.ok for result in results)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
