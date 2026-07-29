#!/usr/bin/env python3
from __future__ import annotations

import gc
import hashlib
import importlib
import inspect
import json
import os
import pkgutil
import py_compile
import re
import shutil
import statistics
import subprocess
import sys
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, TypedDict

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PACKAGE = SRC / "sophyane"
OUT = ROOT / "runtime" / "benchmarks"

REPEATS = max(1, int(os.environ.get("BENCH_REPEATS", "3")))
GRAPH_ITERATIONS = max(1, int(os.environ.get("GRAPH_ITERATIONS", "30")))
TIMEOUT = max(10, int(os.environ.get("BENCH_TIMEOUT_SECONDS", "180")))

# Prevent accidental provider use or unattended installation where supported.
os.environ.setdefault("SOPHYANE_AUTO_INSTALL_NATIVE", "0")
os.environ.setdefault("SOPHYANE_NATIVE_AUTO_FETCH", "0")
os.environ.setdefault("SOPHYANE_OFFLINE", "1")
os.environ.setdefault("LANGSMITH_TRACING", "false")


@dataclass
class Result:
    category: str
    name: str
    system: str
    status: str
    validated: bool
    elapsed_ms: float
    detail: str
    error: str = ""
    comparable: bool = False


RESULTS: list[Result] = []


def _sophyane_terminals(graph):
    """Return (start, end) markers that Sophyane compile() recognizes."""
    start = getattr(graph, "START", None) or getattr(type(graph), "START", "START")
    end = getattr(graph, "END", None) or getattr(type(graph), "END", "END")
    return start, end



def compact(value: Any, limit: int = 5000) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        return text[:limit] + "\n...[truncated]"
    return text


def record(
    category: str,
    name: str,
    system: str,
    status: str,
    validated: bool,
    elapsed_ms: float,
    detail: Any = "",
    error: Any = "",
    comparable: bool = False,
) -> Result:
    result = Result(
        category=category,
        name=name,
        system=system,
        status=status,
        validated=validated,
        elapsed_ms=round(elapsed_ms, 3),
        detail=compact(detail),
        error=compact(error),
        comparable=comparable,
    )
    RESULTS.append(result)

    icon = {
        "PASS": "PASS",
        "FAIL": "FAIL",
        "SKIP": "SKIP",
        "WARN": "WARN",
    }.get(status, status)

    print(
        f"[{icon:4}] {system:10} | {category:18} | "
        f"{name:39} | {elapsed_ms:10.3f} ms"
    )
    if error:
        print(f"       error: {compact(error, 300)}")

    return result


def timed_call(fn: Callable[[], Any]) -> tuple[bool, Any, float, str]:
    started = time.perf_counter()
    try:
        value = fn()
        return True, value, (time.perf_counter() - started) * 1000.0, ""
    except Exception as exc:
        return (
            False,
            None,
            (time.perf_counter() - started) * 1000.0,
            f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
        )


def run_process(
    command: list[str],
    timeout: int = TIMEOUT,
    env: dict[str, str] | None = None,
) -> tuple[bool, str, float, str]:
    started = time.perf_counter()
    full_env = os.environ.copy()
    if env:
        full_env.update(env)

    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=full_env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        elapsed = (time.perf_counter() - started) * 1000.0
        output = "\n".join(
            x for x in (completed.stdout, completed.stderr) if x
        ).strip()

        if completed.returncode == 0:
            return True, output, elapsed, ""

        return (
            False,
            output,
            elapsed,
            f"exit code {completed.returncode}",
        )

    except subprocess.TimeoutExpired as exc:
        elapsed = (time.perf_counter() - started) * 1000.0
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""

        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")

        return (
            False,
            f"{stdout}\n{stderr}".strip(),
            elapsed,
            f"timeout after {timeout}s",
        )

    except Exception as exc:
        return (
            False,
            "",
            (time.perf_counter() - started) * 1000.0,
            f"{type(exc).__name__}: {exc}",
        )


def executable(candidates: list[Any]) -> str | None:
    for value in candidates:
        if not value:
            continue

        path = Path(str(value)).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())

        found = shutil.which(str(value))
        if found:
            return str(Path(found).resolve())

    return None


NIFDU = executable(
    [
        os.environ.get("SOPHYANE_NIFDU_BIN"),
        Path.home() / ".local/bin/nifdu",
        Path.home() / "nifdu/build/nifdu",
        "nifdu",
    ]
)

NEURON = executable(
    [
        os.environ.get("SOPHYANE_NEURON_BIN"),
        Path.home() / "neuron_repo/build/test_neuron_capabilities",
        Path.home() / "nifdu/build/test_neuron_capabilities",
        "test_neuron_capabilities",
    ]
)


# ===========================================================================
# A. Repository and source health
# ===========================================================================

def test_source_compilation() -> None:
    files = sorted(PACKAGE.rglob("*.py"))
    failures: list[str] = []
    started = time.perf_counter()

    for file in files:
        try:
            py_compile.compile(str(file), doraise=True)
        except Exception as exc:
            failures.append(f"{file.relative_to(ROOT)}: {exc}")

    elapsed = (time.perf_counter() - started) * 1000.0
    record(
        "Repository",
        f"compile {len(files)} Python sources",
        "Sophyane",
        "PASS" if not failures else "FAIL",
        not failures and bool(files),
        elapsed,
        f"files={len(files)}",
        "\n".join(failures),
    )


def discover_modules() -> list[str]:
    names = []
    for module in pkgutil.iter_modules([str(PACKAGE)]):
        names.append(f"sophyane.{module.name}")
    return sorted(names)


def test_import_health() -> None:
    modules = discover_modules()
    imported: list[str] = []
    failed: dict[str, str] = {}

    started = time.perf_counter()

    for name in modules:
        try:
            importlib.import_module(name)
            imported.append(name)
        except SystemExit as exc:
            failed[name] = f"SystemExit: {exc}"
        except Exception as exc:
            failed[name] = f"{type(exc).__name__}: {exc}"

    elapsed = (time.perf_counter() - started) * 1000.0

    # Some CLI modules may intentionally act on import. Record partial health,
    # but require at least the principal runtime modules.
    principal = {
        "sophyane.agent",
        "sophyane.graph_runtime",
        "sophyane.native_capability",
        "sophyane.native_backends",
        "sophyane.capability_registry",
        "sophyane.capability_executors",
    }

    missing_principal = sorted(principal - set(imported))
    status = "PASS" if not missing_principal else "FAIL"

    record(
        "Repository",
        f"module import inventory ({len(modules)})",
        "Sophyane",
        status,
        not missing_principal,
        elapsed,
        json.dumps(
            {
                "discovered": len(modules),
                "imported": len(imported),
                "failed": failed,
                "missing_principal": missing_principal,
            },
            indent=2,
        ),
        "\n".join(missing_principal),
    )


# ===========================================================================
# B. Static capability inventory
# ===========================================================================

CAPABILITY_WORDS = re.compile(
    r"\b("
    r"capability|executor|action|tool|policy|ontology|intent|"
    r"workflow|backend|worker|stategraph|memory|provider"
    r")\b",
    re.I,
)


def test_capability_inventory() -> None:
    rows: list[dict[str, Any]] = []
    started = time.perf_counter()

    for file in sorted(PACKAGE.rglob("*.py")):
        try:
            text = file.read_text(encoding="utf-8")
        except Exception:
            continue

        functions = re.findall(
            r"^(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)",
            text,
            re.M,
        )
        classes = re.findall(
            r"^class\s+([A-Za-z_][A-Za-z0-9_]*)",
            text,
            re.M,
        )
        markers = sorted(
            set(match.group(1).lower() for match in CAPABILITY_WORDS.finditer(text))
        )

        if markers:
            rows.append(
                {
                    "file": str(file.relative_to(ROOT)),
                    "functions": functions,
                    "classes": classes,
                    "markers": markers,
                }
            )

    elapsed = (time.perf_counter() - started) * 1000.0

    inventory_path = OUT / "sophyane-capability-inventory.json"
    inventory_path.write_text(
        json.dumps(rows, indent=2),
        encoding="utf-8",
    )

    record(
        "Discovery",
        "static capability inventory",
        "Sophyane",
        "PASS" if rows else "FAIL",
        bool(rows),
        elapsed,
        f"evidence_files={len(rows)}\nreport={inventory_path}",
    )


def inspect_module(module_name: str) -> dict[str, Any]:
    module = importlib.import_module(module_name)

    functions = {}
    classes = {}

    for name, value in inspect.getmembers(module):
        if name.startswith("_"):
            continue
        if inspect.isfunction(value) and value.__module__ == module_name:
            try:
                signature = str(inspect.signature(value))
            except Exception:
                signature = "(unknown)"
            functions[name] = signature
        elif inspect.isclass(value) and value.__module__ == module_name:
            classes[name] = {}

    return {
        "module": module_name,
        "functions": functions,
        "classes": classes,
    }


def test_runtime_surface_inventory() -> None:
    candidates = [
        "sophyane.capability_registry",
        "sophyane.capability_executors",
        "sophyane.capability_gap",
        "sophyane.capability_gap_messages",
        "sophyane.native_backends",
        "sophyane.native_capability",
        "sophyane.collaborative_workers",
        "sophyane.graph_runtime",
        "sophyane.execution_runtime",
        "sophyane.adaptive_execution",
        "sophyane.goal_execution",
        "sophyane.memory",
    ]

    found = []
    errors = {}

    started = time.perf_counter()
    for module_name in candidates:
        try:
            found.append(inspect_module(module_name))
        except Exception as exc:
            errors[module_name] = f"{type(exc).__name__}: {exc}"

    elapsed = (time.perf_counter() - started) * 1000.0

    path = OUT / "sophyane-runtime-surfaces.json"
    path.write_text(
        json.dumps(
            {"modules": found, "errors": errors},
            indent=2,
        ),
        encoding="utf-8",
    )

    record(
        "Discovery",
        "runtime callable surfaces",
        "Sophyane",
        "PASS" if found else "FAIL",
        bool(found),
        elapsed,
        f"loaded={len(found)}/{len(candidates)}\nreport={path}",
        json.dumps(errors, indent=2) if errors else "",
    )


# ===========================================================================
# C. Native backends and routing
# ===========================================================================

def test_native_probe() -> None:
    def action():
        from sophyane.native_backends import status
        return status()

    ok, value, elapsed, error = timed_call(action)
    text = compact(value)
    valid = ok and "nifdu" in text.lower() and "neuron" in text.lower()

    record(
        "Native",
        "backend status probe",
        "Sophyane",
        "PASS" if ok and valid else "FAIL",
        valid,
        elapsed,
        text,
        error,
    )


def native_reply(prompt: str) -> tuple[bool, Any, float, str]:
    def action():
        from sophyane.native_capability import try_any_native_reply
        return try_any_native_reply(prompt)

    return timed_call(action)


def test_native_routes() -> None:
    cases = [
        (
            "native status route",
            "show native workers status",
            ("nifdu", "neuron"),
        ),
        (
            "NIFDU availability route",
            "is nifdu installed",
            ("nifdu",),
        ),
        (
            "Neuron availability route",
            "is neuron installed",
            ("neuron",),
        ),
        (
            "combined NIFDU and Neuron route",
            "use nifdu and neuron — run neuron capabilities benchmark",
            ("llm=false", "nifdu=true", "neuron=true"),
        ),
    ]

    for name, prompt, expected in cases:
        ok, value, elapsed, error = native_reply(prompt)
        text = compact(value)
        normalized = text.casefold()

        valid = (
            ok
            and bool(text)
            and all(marker.casefold() in normalized for marker in expected)
        )

        record(
            "Native routing",
            name,
            "Sophyane",
            "PASS" if valid else "FAIL",
            valid,
            elapsed,
            text,
            error,
        )


def test_native_binaries() -> None:
    started = time.perf_counter()
    detail: dict[str, Any] = {}

    for name, binary in (("nifdu", NIFDU), ("neuron", NEURON)):
        if not binary:
            detail[name] = {"available": False}
            continue

        path = Path(binary)
        detail[name] = {
            "available": True,
            "path": str(path),
            "size": path.stat().st_size,
            "executable": os.access(path, os.X_OK),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    valid = (
        detail.get("nifdu", {}).get("available", False)
        and detail.get("neuron", {}).get("available", False)
    )

    record(
        "Native",
        "binary integrity and identity",
        "Sophyane",
        "PASS" if valid else "WARN",
        valid,
        (time.perf_counter() - started) * 1000.0,
        json.dumps(detail, indent=2),
    )


def test_neuron_direct() -> None:
    if not NEURON:
        record(
            "Native",
            "direct Neuron capability audit",
            "Neuron",
            "SKIP",
            False,
            0.0,
            "Neuron executable not found",
        )
        return

    ok, output, elapsed, error = run_process([NEURON])
    lower = output.casefold()
    valid = ok and (
        "6/6 tests passed" in lower
        or "100% success" in lower
    )

    record(
        "Native",
        "direct Neuron capability audit",
        "Neuron",
        "PASS" if valid else "FAIL",
        valid,
        elapsed,
        output,
        error,
    )


# ===========================================================================
# D. Deterministic execution and gap handling
# ===========================================================================

def test_deterministic_executor() -> None:
    prompts = [
        "count folders in a directory",
        "list files in the current workspace",
        "check native workers status",
    ]

    try:
        from sophyane.capability_executors import execute_deterministic_text
    except Exception as exc:
        record(
            "Executor",
            "deterministic executor import",
            "Sophyane",
            "FAIL",
            False,
            0.0,
            "",
            exc,
        )
        return

    for prompt in prompts:
        started = time.perf_counter()
        error = ""
        value = None

        try:
            value = execute_deterministic_text(prompt)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        elapsed = (time.perf_counter() - started) * 1000.0

        # None is acceptable when the registry correctly declines a task.
        status = "PASS" if not error else "FAIL"
        record(
            "Executor",
            f"safe dispatch: {prompt}",
            "Sophyane",
            status,
            not error,
            elapsed,
            repr(value),
            error,
        )


def test_capability_gap() -> None:
    candidates = [
        (
            "sophyane.capability_gap_messages",
            "capability_gap_reply",
        ),
        (
            "sophyane.capability_gap",
            "capability_gap_reply",
        ),
    ]

    fn = None
    source = ""

    for module_name, function_name in candidates:
        try:
            module = importlib.import_module(module_name)
            candidate = getattr(module, function_name, None)
            if callable(candidate):
                fn = candidate
                source = f"{module_name}.{function_name}"
                break
        except Exception:
            pass

    if fn is None:
        record(
            "Policy",
            "capability-gap surface",
            "Sophyane",
            "SKIP",
            False,
            0.0,
            "No safe capability_gap_reply callable found",
        )
        return

    ok, value, elapsed, error = timed_call(
        lambda: fn(
            "teleport this computer physically to Mars using no hardware"
        )
    )

    record(
        "Policy",
        "capability-gap response",
        "Sophyane",
        "PASS" if ok else "FAIL",
        ok,
        elapsed,
        f"callable={source}\nreply={value!r}",
        error,
    )


# ===========================================================================
# E. Sophyane vs LangGraph graph comparison
# ===========================================================================

class GraphState(TypedDict, total=False):
    value: int
    route: str
    trace: list[str]


def load_graph_classes():
    """Return graph classes with *matching* START/END sentinels per framework."""
    from sophyane.graph_runtime import StateGraph as SophyaneStateGraph
    from langgraph.graph import StateGraph as LangStateGraph, START, END

    # Sophyane uses plain string sentinels on the class (not LangGraph objects).
    sophyane_start = getattr(SophyaneStateGraph, "START", "START")
    sophyane_end = getattr(SophyaneStateGraph, "END", "END")
    return (
        SophyaneStateGraph,
        LangStateGraph,
        sophyane_start,
        sophyane_end,
        START,
        END,
    )



def build_linear(Graph: Any, start: Any, end: Any):
    def a(state):
        return {
            "value": state.get("value", 0) + 1,
            "trace": state.get("trace", []) + ["a"],
        }

    def b(state):
        return {
            "value": state.get("value", 0) * 2,
            "trace": state.get("trace", []) + ["b"],
        }

    def c(state):
        return {
            "value": state.get("value", 0) + 10,
            "trace": state.get("trace", []) + ["c"],
        }

    try:
        graph = Graph(GraphState)
    except TypeError:
        graph = Graph()
    graph.add_node("a", a)
    graph.add_node("b", b)
    graph.add_node("c", c)
    graph.add_edge(start, "a")
    graph.add_edge("a", "b")
    graph.add_edge("b", "c")
    graph.add_edge("c", end)
    return graph.compile()


def build_conditional(Graph: Any, start: Any, end: Any):
    def classify(state):
        value = state.get("value", 0)
        return {
            "route": "even" if value % 2 == 0 else "odd",
            "trace": state.get("trace", []) + ["classify"],
        }

    def even(state):
        return {
            "value": state.get("value", 0) + 100,
            "trace": state.get("trace", []) + ["even"],
        }

    def odd(state):
        return {
            "value": state.get("value", 0) + 200,
            "trace": state.get("trace", []) + ["odd"],
        }

    try:
        graph = Graph(GraphState)
    except TypeError:
        graph = Graph()
    graph.add_node("classify", classify)
    graph.add_node("even", even)
    graph.add_node("odd", odd)
    graph.add_edge(start, "classify")

    if hasattr(graph, "add_conditional_edges"):
        graph.add_conditional_edges(
            "classify",
            lambda state: state["route"],
            {"even": "even", "odd": "odd"},
        )
    else:
        raise RuntimeError("conditional edges unsupported")

    graph.add_edge("even", end)
    graph.add_edge("odd", end)
    return graph.compile()


def build_long_chain(Graph: Any, start: Any, end: Any, count: int = 10):
    try:
        graph = Graph(GraphState)
    except TypeError:
        graph = Graph()

    for index in range(count):
        def node(state, i=index):
            return {
                "value": state.get("value", 0) + 1,
                "trace": state.get("trace", []) + [str(i)],
            }

        graph.add_node(f"n{index}", node)

    graph.add_edge(start, "n0")
    for index in range(count - 1):
        graph.add_edge(f"n{index}", f"n{index + 1}")
    graph.add_edge(f"n{count - 1}", end)

    return graph.compile()


def benchmark_invocation(
    app: Any,
    initial: dict[str, Any],
    validator: Callable[[dict[str, Any]], bool],
) -> tuple[bool, float, dict[str, Any], str]:
    times = []
    final: dict[str, Any] = {}

    try:
        # Warm-up
        final = app.invoke(dict(initial))

        for _ in range(GRAPH_ITERATIONS):
            gc.collect()
            started = time.perf_counter()
            final = app.invoke(dict(initial))
            times.append((time.perf_counter() - started) * 1000.0)

        valid = validator(final)

        return (
            valid,
            statistics.median(times),
            {
                "iterations": GRAPH_ITERATIONS,
                "mean_ms": round(statistics.fmean(times), 6),
                "median_ms": round(statistics.median(times), 6),
                "min_ms": round(min(times), 6),
                "max_ms": round(max(times), 6),
                "ops_per_second": round(
                    1000.0 / statistics.fmean(times), 3
                ),
                "final": final,
            },
            "",
        )

    except Exception as exc:
        return (
            False,
            0.0,
            final,
            f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
        )


def test_graphs() -> None:
    try:
        (
            SG,
            LG,
            SOPHYANE_START,
            SOPHYANE_END,
            LANGGRAPH_START,
            LANGGRAPH_END,
        ) = load_graph_classes()
    except Exception as exc:
        record(
            "Graph",
            "load graph runtimes",
            "Both",
            "FAIL",
            False,
            0.0,
            "",
            exc,
            True,
        )
        return

    # Keep framework-specific sentinels separate.
    sophyane_start = SOPHYANE_START
    sophyane_end = SOPHYANE_END
    langgraph_start = LANGGRAPH_START
    langgraph_end = LANGGRAPH_END

    workloads = [
        (
            "linear three-node graph",
            build_linear,
            {"value": 5, "trace": []},
            lambda state: (
                state.get("value") == 22
                and state.get("trace") == ["a", "b", "c"]
            ),
        ),
        (
            "conditional branch graph",
            build_conditional,
            {"value": 4, "trace": []},
            lambda state: (
                state.get("value") == 104
                and "even" in state.get("trace", [])
            ),
        ),
        (
            "ten-node sequential graph",
            build_long_chain,
            {"value": 0, "trace": []},
            lambda state: (
                state.get("value") == 10
                and len(state.get("trace", [])) == 10
            ),
        ),
    ]

    for name, builder, initial, validator in workloads:
        for system, Graph, start, end in (
            ("Sophyane", SG, sophyane_start, sophyane_end),
            ("LangGraph", LG, langgraph_start, langgraph_end),
        ):
            build_ok, app, build_ms, build_error = timed_call(
                lambda b=builder, g=Graph, s=start, e=end: b(g, s, e)
            )

            if not build_ok:
                record(
                    "Graph build",
                    name,
                    system,
                    "FAIL",
                    False,
                    build_ms,
                    "",
                    build_error,
                    True,
                )
                continue

            record(
                "Graph build",
                name,
                system,
                "PASS",
                True,
                build_ms,
                "compiled",
                "",
                True,
            )

            valid, median_ms, detail, error = benchmark_invocation(
                app,
                initial,
                validator,
            )

            record(
                "Graph execution",
                name,
                system,
                "PASS" if valid else "FAIL",
                valid,
                median_ms,
                json.dumps(detail, indent=2),
                error,
                True,
            )


# ===========================================================================
# F. CLI smoke test
# ===========================================================================

def test_cli() -> None:
    code = r'''
import builtins
import runpy

responses = iter(["/quit"])

def fake_input(prompt=""):
    try:
        return next(responses)
    except StopIteration:
        raise EOFError

builtins.input = fake_input
runpy.run_module("sophyane", run_name="__main__")
'''

    ok, output, elapsed, error = run_process(
        [sys.executable, "-c", code],
        timeout=30,
        env={
            "PYTHONPATH": str(SRC),
            "SOPHYANE_OFFLINE": "1",
        },
    )

    normalized = output.casefold()
    valid = ok and (
        "sophyane" in normalized
        or not output
    )

    record(
        "CLI",
        "startup and controlled exit",
        "Sophyane",
        "PASS" if valid else "FAIL",
        valid,
        elapsed,
        output,
        error,
    )


# ===========================================================================
# G. Reporting
# ===========================================================================

def aggregate() -> dict[str, Any]:
    systems: dict[str, Any] = {}

    for system in sorted(set(result.system for result in RESULTS)):
        subset = [result for result in RESULTS if result.system == system]
        measured = [
            result.elapsed_ms
            for result in subset
            if result.status not in {"SKIP"}
        ]

        systems[system] = {
            "tests": len(subset),
            "pass": sum(result.status == "PASS" for result in subset),
            "fail": sum(result.status == "FAIL" for result in subset),
            "warn": sum(result.status == "WARN" for result in subset),
            "skip": sum(result.status == "SKIP" for result in subset),
            "validated": sum(result.validated for result in subset),
            "mean_ms": round(
                statistics.fmean(measured), 3
            ) if measured else 0.0,
            "median_ms": round(
                statistics.median(measured), 3
            ) if measured else 0.0,
        }

    return systems


def paired_graph_summary() -> list[dict[str, Any]]:
    rows = []

    names = sorted(
        {
            result.name
            for result in RESULTS
            if result.category == "Graph execution"
        }
    )

    for name in names:
        soph = next(
            (
                result for result in RESULTS
                if result.category == "Graph execution"
                and result.name == name
                and result.system == "Sophyane"
            ),
            None,
        )
        lang = next(
            (
                result for result in RESULTS
                if result.category == "Graph execution"
                and result.name == name
                and result.system == "LangGraph"
            ),
            None,
        )

        if not soph or not lang:
            continue

        if soph.elapsed_ms > 0 and lang.elapsed_ms > 0:
            if soph.elapsed_ms < lang.elapsed_ms:
                winner = "Sophyane"
                ratio = lang.elapsed_ms / soph.elapsed_ms
            elif lang.elapsed_ms < soph.elapsed_ms:
                winner = "LangGraph"
                ratio = soph.elapsed_ms / lang.elapsed_ms
            else:
                winner = "Tie"
                ratio = 1.0
        else:
            winner = "Unavailable"
            ratio = 0.0

        rows.append(
            {
                "workload": name,
                "sophyane_median_ms": soph.elapsed_ms,
                "langgraph_median_ms": lang.elapsed_ms,
                "winner": winner,
                "speed_ratio": round(ratio, 3),
                "both_validated": soph.validated and lang.validated,
            }
        )

    return rows


def write_report() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    summary = aggregate()
    graph_comparison = paired_graph_summary()

    payload = {
        "generated_at": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(),
        ),
        "configuration": {
            "python": sys.version,
            "root": str(ROOT),
            "repeats": REPEATS,
            "graph_iterations": GRAPH_ITERATIONS,
            "timeout_seconds": TIMEOUT,
            "nifdu": NIFDU,
            "neuron": NEURON,
            "cloud_provider_execution_requested": False,
        },
        "summary": summary,
        "graph_comparison": graph_comparison,
        "results": [asdict(result) for result in RESULTS],
    }

    json_path = OUT / f"comprehensive-capabilities-{stamp}.json"
    md_path = OUT / f"comprehensive-capabilities-{stamp}.md"
    latest_json = OUT / "comprehensive-capabilities-latest.json"
    latest_md = OUT / "comprehensive-capabilities-latest.md"

    json_text = json.dumps(payload, indent=2, ensure_ascii=False)
    json_path.write_text(json_text, encoding="utf-8")
    latest_json.write_text(json_text, encoding="utf-8")

    lines = [
        "# Sophyane comprehensive capability test",
        "",
        f"Generated: `{payload['generated_at']}`",
        "",
        "## Scope",
        "",
        "- Safe discovery and execution of locally available Sophyane surfaces",
        "- NIFDU and Neuron probing",
        "- Deterministic and policy routing",
        "- Equivalent Sophyane/LangGraph graph workloads",
        "- No intentional Gemini/provider requests",
        "- No repository mutation or native auto-installation",
        "",
        "## Aggregate",
        "",
        "| System | Tests | Pass | Fail | Warn | Skip | Validated |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]

    for system, data in summary.items():
        lines.append(
            f"| {system} | {data['tests']} | {data['pass']} | "
            f"{data['fail']} | {data['warn']} | {data['skip']} | "
            f"{data['validated']} |"
        )

    lines.extend(
        [
            "",
            "## Paired graph comparison",
            "",
            "| Workload | Sophyane median ms | LangGraph median ms | Winner | Ratio | Valid |",
            "|---|---:|---:|---|---:|:---:|",
        ]
    )

    for row in graph_comparison:
        lines.append(
            f"| {row['workload']} "
            f"| {row['sophyane_median_ms']:.6f} "
            f"| {row['langgraph_median_ms']:.6f} "
            f"| {row['winner']} "
            f"| {row['speed_ratio']:.3f}x "
            f"| {'yes' if row['both_validated'] else 'no'} |"
        )

    lines.extend(
        [
            "",
            "## All tests",
            "",
            "| Category | Test | System | Status | Valid | Time ms |",
            "|---|---|---|:---:|:---:|---:|",
        ]
    )

    for result in RESULTS:
        lines.append(
            f"| {result.category} | {result.name} | {result.system} "
            f"| {result.status} "
            f"| {'yes' if result.validated else 'no'} "
            f"| {result.elapsed_ms:.3f} |"
        )

    failures = [
        result for result in RESULTS
        if result.status == "FAIL"
    ]

    lines.extend(["", "## Failures", ""])

    if not failures:
        lines.append("No test failures.")
    else:
        for result in failures:
            lines.append(
                f"### {result.system}: {result.name}\n\n"
                f"```text\n{result.error or result.detail}\n```"
            )

    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "This test covers all safely discoverable local capability surfaces. "
            "It does not execute arbitrary filesystem mutation, browser activity, "
            "cloud-provider calls, credential operations, deployments, or other "
            "potentially destructive capabilities.",
            "",
        ]
    )

    markdown = "\n".join(lines)
    md_path.write_text(markdown, encoding="utf-8")
    latest_md.write_text(markdown, encoding="utf-8")

    print()
    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)

    for system, data in summary.items():
        print(
            f"{system:10} tests={data['tests']:2} "
            f"pass={data['pass']:2} fail={data['fail']:2} "
            f"warn={data['warn']:2} skip={data['skip']:2} "
            f"validated={data['validated']:2}"
        )

    print()
    print("Paired graph workloads:")
    for row in graph_comparison:
        print(
            f"  {row['workload']:<34} "
            f"winner={row['winner']:<10} "
            f"ratio={row['speed_ratio']:.3f}x "
            f"valid={row['both_validated']}"
        )

    print()
    print(f"JSON     : {json_path}")
    print(f"Markdown : {md_path}")
    print(f"Latest   : {latest_md}")

    # Exit failure only for actual FAIL results. WARN/SKIP remain reportable.
    if failures:
        raise SystemExit(1)


def main() -> None:
    print(f"Root             : {ROOT}")
    print(f"Python           : {sys.version.split()[0]}")
    print(f"NIFDU            : {NIFDU or 'not found'}")
    print(f"Neuron           : {NEURON or 'not found'}")
    print(f"Graph iterations : {GRAPH_ITERATIONS}")
    print()

    test_source_compilation()
    test_import_health()
    test_capability_inventory()
    test_runtime_surface_inventory()

    test_native_binaries()
    test_native_probe()
    test_native_routes()
    test_neuron_direct()

    test_deterministic_executor()
    test_capability_gap()

    test_graphs()
    test_cli()

    write_report()


if __name__ == "__main__":
    main()
