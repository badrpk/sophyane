"""Isolated, frozen-input RSI transfer evaluations.

The harness gives a solver only a task id, domain label, and prompt. Rubric
answers stay in the evaluator process. This is process/workspace isolation, not
an OS sandbox: commands can still access files permitted to their user.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import ast
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import signal
import subprocess
import tempfile
import time
from typing import Mapping, Sequence


BENCHMARK_VERSION = "sophyane-transfer-2026-10-v2"
RUBRIC_VERSION = "sophyane-transfer-rubric-v2"
DOMAINS = frozenset({"mathematical_reasoning", "code_repair", "formal_theorem_proving"})


@dataclass(frozen=True, slots=True)
class BenchmarkTask:
    task_id: str
    domain: str
    prompt: str
    rubric: str
    expected: str
    grader: str = "normalized_exact"
    hidden_tests: tuple = ()
    function_name: str = ""


@dataclass(frozen=True, slots=True)
class RunRecord:
    task_id: str
    domain: str
    repetition: int
    outcome: str
    correct: bool
    elapsed_seconds: float
    peak_rss_bytes: int | None
    return_code: int | None
    error: str = ""


@dataclass(frozen=True, slots=True)
class SnapshotReport:
    system_version: str
    benchmark_version: str
    rubric_version: str
    holdout_hash: str
    rubric_hash: str
    holdout_attested: bool
    repetitions: int
    task_count: int
    domain_count: int
    correctness: float | None
    reliability: float
    infrastructure_failures: int
    mean_runtime_seconds: float | None
    mean_peak_rss_bytes: float | None
    domain_correctness: Mapping[str, float]
    runs: tuple[RunRecord, ...]


@dataclass(frozen=True, slots=True)
class TransferBenchmarkReport:
    status: str
    task_count: int
    domain_count: int
    infrastructure_task_count: int
    correctness_delta: float | None
    correctness_ci_low: float | None
    correctness_ci_high: float | None
    reliability_delta: float
    runtime_delta_seconds: float | None
    peak_rss_delta_bytes: float | None
    exact_sign_test_p: float
    statistically_significant: bool
    holdout_hash: str
    rubric_hash: str
    domains: Mapping[str, float]
    interpretation: str


@dataclass(frozen=True, slots=True)
class PairedBenchmarkRun:
    baseline: SnapshotReport
    post: SnapshotReport
    comparison: TransferBenchmarkReport


def frozen_tasks() -> tuple[BenchmarkTask, ...]:
    """Return the versioned six-task holdout; do not expose expected fields to solvers."""
    return (
        BenchmarkTask(
            "math-ode-01", "mathematical_reasoning",
            "Solve y'=-2y, y(0)=3. Return the closed form for y(t), then y(1), in one line.",
            "math-exact-v1", "y(t)=3e^(-2t); y(1)=3e^(-2)",
        ),
        BenchmarkTask(
            "math-heat-02", "mathematical_reasoning",
            "For the 1D FTCS heat scheme with r=nu*dt/dx^2, state the necessary and sufficient von Neumann stability interval for r.",
            "math-exact-v1", "0 <= r <= 1/2",
        ),
        BenchmarkTask(
            "code-sort-01", "code_repair",
            "Repair this Python function so it returns sorted unique values: def normalize(xs):\n    return sorted(xs)",
            "code-patch-exact-v1", "def normalize(xs):\n    return sorted(set(xs))",
        ),
        BenchmarkTask(
            "code-index-02", "code_repair",
            "Repair this function so it returns the last element, or None for empty input: def last_or_none(xs):\n    return xs[len(xs)]",
            "code-patch-exact-v1", "def last_or_none(xs):\n    return xs[-1] if xs else None",
        ),
        BenchmarkTask(
            "lean-nat-01", "formal_theorem_proving",
            "Give a Lean 4 declaration proving 0 + n = n for every natural n. Return only the declaration.",
            "lean-compile-v1", "theorem transfer_zero_add (n : Nat) : 0 + n = n := by rfl",
            "lean_compile",
        ),
        BenchmarkTask(
            "lean-nat-02", "formal_theorem_proving",
            "Give a Lean 4 declaration proving n + 0 = n for every natural n. Return only the declaration.",
            "lean-compile-v1", "theorem transfer_add_zero (n : Nat) : n + 0 = n := by rfl",
            "lean_compile",
        ),
    )


def load_tasks_file(path: str | Path) -> tuple[BenchmarkTask, ...]:
    """Load a frozen evaluator-only task pack; callers must not mount it in solver roots."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if (payload.get("benchmark_version") != BENCHMARK_VERSION
            or payload.get("rubric_version") != RUBRIC_VERSION):
        raise ValueError("task pack benchmark/rubric version mismatch")
    raw_tasks = payload.get("tasks")
    if not isinstance(raw_tasks, list):
        raise ValueError("task pack must contain a tasks array")
    tasks = tuple(BenchmarkTask(
        task_id=str(item["task_id"]), domain=str(item["domain"]),
        prompt=str(item["prompt"]), rubric=str(item["rubric"]),
        expected=str(item.get("expected", "")), grader=str(item.get("grader", "normalized_exact")),
        hidden_tests=tuple((tuple(case["args"]), case["expected"]) for case in item.get("hidden_tests", [])),
        function_name=str(item.get("function_name", "")),
    ) for item in raw_tasks)
    _validate_tasks(tasks)
    return tasks


def _normalized(text: str) -> str:
    return " ".join(text.strip().split())


def _hash_tasks(tasks: Sequence[BenchmarkTask], *, rubric_only: bool = False) -> str:
    if rubric_only:
        content = [(task.task_id, task.domain, task.rubric, task.grader, task.expected,
                    task.hidden_tests, task.function_name) for task in tasks]
    else:
        content = [(task.task_id, task.domain, task.prompt) for task in tasks]
    raw = json.dumps(content, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _validate_tasks(tasks: Sequence[BenchmarkTask]) -> None:
    if not tasks:
        raise ValueError("benchmark requires at least one task")
    ids = [task.task_id for task in tasks]
    if len(ids) != len(set(ids)) or any(not item.strip() for item in ids):
        raise ValueError("task ids must be non-empty and unique")
    if any(task.domain not in DOMAINS for task in tasks):
        raise ValueError("unknown benchmark domain")
    if any(not task.prompt.strip() or not task.rubric.strip() for task in tasks):
        raise ValueError("task prompts and rubric identifiers must be non-empty")
    if any(task.grader not in {"normalized_exact", "integer_final", "lean_compile", "python_cases"} for task in tasks):
        raise ValueError("unsupported grader")
    if any(task.grader == "python_cases" and (not task.function_name or not task.hidden_tests) for task in tasks):
        raise ValueError("Python case grader requires a function name and hidden cases")


def _grade(
    task: BenchmarkTask, answer: str, workspace: Path,
    *, lean_command: Sequence[str] | None = None,
) -> tuple[bool, str]:
    if task.grader == "normalized_exact":
        return _normalized(answer) == _normalized(task.expected), ""
    if task.grader == "integer_final":
        final = re.findall(r"(?:final answer|answer|remainder|area|value)\s*(?:is|:|=)?\s*([-+]?\d+)", answer, re.I)
        matches = final or re.findall(r"(?<!\w)[-+]?\d+(?!\w)(?!\.\d)", answer)
        if not matches:
            return False, "no integer answer found"
        return matches[-1] == task.expected.strip(), ""
    if task.grader == "python_cases":
        fenced = re.findall(r"```(?:python)?\s*\n(.*?)```", answer, flags=re.I | re.S)
        if fenced:
            answer = fenced[-1].strip()
        try:
            tree = ast.parse(answer)
        except SyntaxError as error:
            return False, f"code syntax error: {error.msg}"
        if (len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef)
                or tree.body[0].name != task.function_name):
            return False, "answer must define exactly the requested function"
        function = tree.body[0]
        builtins = {"len": len, "set": set, "sorted": sorted, "abs": abs,
                    "min": min, "max": max, "sum": sum, "all": all, "any": any}
        allowed_nodes = {
            ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.If,
            ast.IfExp, ast.Expr, ast.Constant, ast.Name, ast.Load, ast.Store, ast.List,
            ast.Tuple, ast.Set, ast.Dict, ast.Subscript, ast.Slice, ast.Call,
            ast.keyword, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub,
            ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod, ast.Compare,
            ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
        }
        if any(type(node) not in allowed_nodes for node in ast.walk(tree)):
            return False, "code uses an operation outside the safe grader subset"
        if function.decorator_list or function.args.vararg or function.args.kwarg or function.args.kwonlyargs:
            return False, "function signature is outside the safe grader subset"
        allowed_names = set(builtins) | {arg.arg for arg in function.args.args}
        if any(isinstance(node, ast.Name) and node.id not in allowed_names for node in ast.walk(tree)):
            return False, "code references an unavailable name"
        if any(not isinstance(statement, (ast.Return, ast.If)) for statement in function.body):
            return False, "function body is outside the safe grader subset"
        try:
            namespace: dict[str, object] = {}
            exec(compile(tree, "<candidate>", "exec"), {"__builtins__": builtins}, namespace)
            candidate = namespace[task.function_name]
            for index, case in enumerate(task.hidden_tests):
                result = candidate(*case[0])
                if result != case[1]:
                    return False, f"hidden case {index + 1} failed"
        except Exception as error:
            return False, f"hidden case execution failed: {type(error).__name__}"
        return True, ""
    if re.search(r"\b(?:sorry|admit)\b", answer):
        return False, "incomplete proof token"
    fenced = re.findall(r"```(?:lean)?\s*\n(.*?)```", answer, flags=re.I | re.S)
    if fenced:
        answer = fenced[-1].strip()
    declaration = _normalized(task.expected.split(":=", 1)[0])
    if declaration not in _normalized(answer):
        return False, "expected theorem statement is absent"
    if lean_command is None and shutil.which("lean") is None:
        return False, "infrastructure_error: Lean 4 executable unavailable"
    source = workspace / "candidate.lean"
    source.write_text(answer, encoding="utf-8")
    try:
        command = list(lean_command) if lean_command is not None else [shutil.which("lean") or "lean", str(source)]
        command = [part.replace("{workspace}", str(workspace)).replace("{source}", str(source)) for part in command]
        result = subprocess.run(
            command, cwd=workspace, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=20, check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "grader_timeout: Lean 4"
    except OSError as error:
        return False, f"infrastructure_error: Lean 4 grader unavailable ({type(error).__name__})"
    return result.returncode == 0, result.stdout[-1000:]


def _process_tree_rss_bytes(root_pid: int) -> int:
    """Return current RSS summed over the solver and its visible descendants."""
    parent_by_pid: dict[int, int] = {}
    rss_by_pid: dict[int, int] = {}
    try:
        proc_entries = tuple(Path("/proc").iterdir())
    except OSError:
        return 0
    for entry in proc_entries:
        if not entry.name.isdigit():
            continue
        try:
            status = (entry / "status").read_text()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        ppid_match = re.search(r"^PPid:\s+(\d+)$", status, re.M)
        rss_match = re.search(r"^VmRSS:\s+(\d+)\s+kB$", status, re.M)
        if ppid_match and rss_match:
            pid = int(entry.name)
            parent_by_pid[pid] = int(ppid_match.group(1))
            rss_by_pid[pid] = int(rss_match.group(1)) * 1024
    included = {root_pid}
    changed = True
    while changed:
        before = len(included)
        included.update(pid for pid, ppid in parent_by_pid.items() if ppid in included)
        changed = len(included) != before
    return sum(rss_by_pid.get(pid, 0) for pid in included)


def run_snapshot(
    tasks: Sequence[BenchmarkTask],
    command: Sequence[str],
    *,
    system_version: str,
    repetitions: int = 3,
    timeout_seconds: float = 120.0,
    workspace_root: str | Path | None = None,
    environment: Mapping[str, str] | None = None,
    holdout_attested: bool = False,
    seed: int = 1729,
    lean_command: Sequence[str] | None = None,
) -> SnapshotReport:
    """Run every task repeatedly in a fresh directory and record sampled RSS."""
    _validate_tasks(tasks)
    if not command or repetitions < 1 or timeout_seconds <= 0 or not system_version.strip():
        raise ValueError("command, positive repetitions/timeout, and system version are required")
    root = Path(workspace_root) if workspace_root is not None else None
    records: list[RunRecord] = []
    order_rng = random.Random(seed)
    order = [(task, repeat) for repeat in range(repetitions) for task in tasks]
    order_rng.shuffle(order)

    for task, repetition in order:
        temporary = tempfile.TemporaryDirectory(prefix="sophyane-holdout-", dir=root)
        work = Path(temporary.name)
        payload = json.dumps({"task_id": task.task_id, "domain": task.domain, "prompt": task.prompt})
        # PRoot on Termux needs the host loader variables in its parent process;
        # proot-distro constructs a separate guest environment for the solver.
        env = {key: os.environ[key] for key in (
            "PATH", "LANG", "LC_ALL", "TERM", "PREFIX", "LD_LIBRARY_PATH",
            "LD_PRELOAD", "TERMUX_VERSION",
        ) if key in os.environ}
        env.update({"HOME": str(work), "TMPDIR": str(work)})
        env.update(dict(environment or {}))
        started = time.monotonic()
        peak_rss: int | None = None
        error = ""
        answer = ""
        return_code: int | None = None
        outcome = "error"
        try:
            with (tempfile.TemporaryFile(mode="w+b") as stdout_file,
                  tempfile.TemporaryFile(mode="w+b") as stderr_file,
                  tempfile.TemporaryFile(mode="w+b") as stdin_file):
                stdin_file.write(payload.encode("utf-8"))
                stdin_file.seek(0)
                process = subprocess.Popen(
                    [part.replace("{workspace}", str(work)) for part in command],
                    cwd=work, env=env, stdin=stdin_file,
                    stdout=stdout_file, stderr=stderr_file, start_new_session=True,
                )
                try:
                    while process.poll() is None:
                        peak_rss = max(peak_rss or 0, _process_tree_rss_bytes(process.pid))
                        if time.monotonic() - started > timeout_seconds:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait()
                            outcome = "timeout"
                            error = f"timeout after {timeout_seconds}s"
                            break
                        time.sleep(0.01)
                    return_code = process.returncode
                    stdout_file.seek(0)
                    answer = stdout_file.read(2_000_000).decode("utf-8", errors="replace")
                    if outcome != "timeout":
                        if return_code == 0:
                            outcome = "completed"
                        else:
                            outcome = "nonzero_exit"
                            stderr_file.seek(0)
                            error = stderr_file.read(2000).decode("utf-8", errors="replace")
                except (BrokenPipeError, OSError) as exc:
                    error = f"runner_error: {exc}"
                    process.kill()
                    process.wait()
            elapsed = time.monotonic() - started
            correct = False
            if outcome == "completed":
                correct, grading = _grade(task, answer, work, lean_command=lean_command)
                if grading.startswith("infrastructure_error:"):
                    outcome, error = "infrastructure_error", grading
                elif grading.startswith("grader_timeout:"):
                    outcome, error = "grader_timeout", grading
                elif grading and not correct:
                    error = grading
        except (OSError, ValueError) as exc:
            elapsed = time.monotonic() - started
            correct = False
            error = f"runner_error: {exc}"
        records.append(RunRecord(
            task_id=task.task_id, domain=task.domain, repetition=repetition,
            outcome=outcome, correct=correct, elapsed_seconds=elapsed,
            peak_rss_bytes=peak_rss, return_code=return_code, error=error,
        ))
        temporary.cleanup()

    evaluated = [r for r in records if r.outcome not in {"infrastructure_error", "grader_timeout", "runner_error"}]
    completed = sum(r.return_code == 0 and r.outcome not in {"timeout", "runner_error", "nonzero_exit"}
                    for r in records)
    domain_scores: dict[str, float] = {}
    for domain in sorted({task.domain for task in tasks}):
        rows = [r for r in evaluated if r.domain == domain]
        if rows:
            domain_scores[domain] = sum(r.correct for r in rows) / len(rows)
    rss_values = [r.peak_rss_bytes for r in records if r.peak_rss_bytes is not None]
    return SnapshotReport(
        system_version=system_version,
        benchmark_version=BENCHMARK_VERSION,
        rubric_version=RUBRIC_VERSION,
        holdout_hash=_hash_tasks(tasks),
        rubric_hash=_hash_tasks(tasks, rubric_only=True),
        holdout_attested=holdout_attested,
        repetitions=repetitions,
        task_count=len(tasks),
        domain_count=len({task.domain for task in tasks}),
        correctness=(sum(r.correct for r in evaluated) / len(evaluated)) if evaluated else None,
        reliability=completed / len(records),
        infrastructure_failures=sum(r.outcome in {"infrastructure_error", "grader_timeout", "runner_error"}
                                    for r in records),
        mean_runtime_seconds=math.fsum(r.elapsed_seconds for r in records) / len(records),
        mean_peak_rss_bytes=(math.fsum(rss_values) / len(rss_values)) if rss_values else None,
        domain_correctness=domain_scores,
        runs=tuple(records),
    )


def _task_successes(report: SnapshotReport) -> dict[str, float]:
    grouped: dict[str, list[int]] = {}
    for run in report.runs:
        if run.outcome not in {"infrastructure_error", "grader_timeout", "runner_error"}:
            grouped.setdefault(run.task_id, []).append(int(run.correct))
    return {task: math.fsum(values) / len(values) for task, values in grouped.items()}


def _bootstrap_mean_ci(values: Sequence[float], *, seed: int, samples: int = 20_000) -> tuple[float, float] | None:
    """Deterministic percentile bootstrap over independent task-level deltas."""
    if not values:
        return None
    rng = random.Random(seed)
    count = len(values)
    means = sorted(
        math.fsum(values[rng.randrange(count)] for _ in range(count)) / count
        for _ in range(samples)
    )
    return means[int(0.025 * (samples - 1))], means[int(0.975 * (samples - 1))]


def _exact_sign_test_p(deltas: Sequence[float]) -> float:
    nonzero = [delta for delta in deltas if delta != 0]
    n = len(nonzero)
    if n == 0:
        return 1.0
    positives = sum(delta > 0 for delta in nonzero)
    tail = sum(math.comb(n, k) for k in range(positives, n + 1)) / (2**n)
    return min(1.0, 2.0 * min(tail, 1.0 - tail + math.comb(n, positives) / (2**n)))


def compare_reports(baseline: SnapshotReport, post: SnapshotReport) -> TransferBenchmarkReport:
    if baseline.holdout_hash != post.holdout_hash or baseline.rubric_hash != post.rubric_hash:
        raise ValueError("baseline and post reports must use identical frozen tasks and rubrics")
    if baseline.system_version == post.system_version:
        raise ValueError("baseline and post system versions must be distinct")
    if baseline.benchmark_version != post.benchmark_version or baseline.rubric_version != post.rubric_version:
        raise ValueError("benchmark and rubric versions must match")
    a, b = _task_successes(baseline), _task_successes(post)
    baseline_tasks = {r.task_id for r in baseline.runs}
    post_tasks = {r.task_id for r in post.runs}
    if baseline_tasks != post_tasks:
        raise ValueError("baseline and post reports must include identical task ids")
    paired_tasks = a.keys() & b.keys()
    infrastructure_task_count = len(baseline_tasks - paired_tasks)
    if not paired_tasks:
        return TransferBenchmarkReport(
            status="infrastructure_incomplete", task_count=0, domain_count=0,
            infrastructure_task_count=infrastructure_task_count,
            correctness_delta=None, correctness_ci_low=None, correctness_ci_high=None,
            reliability_delta=post.reliability - baseline.reliability,
            runtime_delta_seconds=None, peak_rss_delta_bytes=None,
            exact_sign_test_p=1.0, statistically_significant=False,
            holdout_hash=baseline.holdout_hash, rubric_hash=baseline.rubric_hash,
            domains={}, interpretation="No task had an available correctness evaluation.",
        )
    domains: dict[str, float] = {}
    deltas = {task: b[task] - a[task] for task in paired_tasks}
    task_domain = {r.task_id: r.domain for r in baseline.runs}
    for domain in sorted({task_domain[task] for task in a}):
        members = [task for task in a if task_domain[task] == domain]
        domains[domain] = math.fsum(deltas[task] for task in members) / len(members)
    p_value = _exact_sign_test_p(list(deltas.values()))
    digest_seed = int(baseline.holdout_hash[:16], 16)
    ci = _bootstrap_mean_ci(list(deltas.values()), seed=digest_seed)
    enough = len(deltas) >= 5 and len(domains) >= 3
    attested = baseline.holdout_attested and post.holdout_attested
    significant = (not infrastructure_task_count and enough and attested and p_value <= 0.05 and ci is not None and ci[0] > 0
                   and all(x >= 0 for x in domains.values()))
    if infrastructure_task_count:
        status, interpretation = "infrastructure_incomplete", "Some tasks lacked valid grading in at least one version; paired evidence is incomplete."
    elif not enough:
        status, interpretation = "insufficient_coverage", "Task or domain minimum not met."
    elif not attested:
        status, interpretation = "holdout_unattested", "The holdout isolation attestation is missing."
    elif significant:
        status, interpretation = "statistically_significant_transfer_signal", "A paired task-level sign test passed; this does not establish causation or broad generalization."
    elif math.fsum(deltas.values()) == 0:
        status, interpretation = "no_gain", "No mean task-level correctness change was observed."
    else:
        status, interpretation = "inconclusive", "Observed changes do not meet the predeclared significance and non-regression criteria."
    return TransferBenchmarkReport(
        status=status, task_count=len(deltas), domain_count=len(domains),
        infrastructure_task_count=infrastructure_task_count,
        correctness_delta=math.fsum(deltas.values()) / len(deltas),
        correctness_ci_low=ci[0] if ci is not None else None,
        correctness_ci_high=ci[1] if ci is not None else None,
        reliability_delta=post.reliability - baseline.reliability,
        runtime_delta_seconds=(post.mean_runtime_seconds - baseline.mean_runtime_seconds)
        if post.mean_runtime_seconds is not None and baseline.mean_runtime_seconds is not None else None,
        peak_rss_delta_bytes=(post.mean_peak_rss_bytes - baseline.mean_peak_rss_bytes)
        if post.mean_peak_rss_bytes is not None and baseline.mean_peak_rss_bytes is not None else None,
        exact_sign_test_p=p_value, statistically_significant=significant,
        holdout_hash=baseline.holdout_hash, rubric_hash=baseline.rubric_hash,
        domains=domains, interpretation=interpretation,
    )


def run_paired_benchmark(
    tasks: Sequence[BenchmarkTask],
    baseline_command: Sequence[str],
    post_command: Sequence[str],
    *,
    baseline_version: str,
    post_version: str,
    repetitions: int = 3,
    timeout_seconds: float = 120.0,
    workspace_root: str | Path | None = None,
    holdout_attested: bool = False,
    seed: int = 1729,
    lean_command: Sequence[str] | None = None,
) -> PairedBenchmarkRun:
    """Run the two versions with matched tasks, rubric, order seed, and limits."""
    common = dict(
        repetitions=repetitions, timeout_seconds=timeout_seconds,
        workspace_root=workspace_root, holdout_attested=holdout_attested,
        seed=seed,
        lean_command=lean_command,
    )
    baseline = run_snapshot(
        tasks, baseline_command, system_version=baseline_version, **common,
    )
    post = run_snapshot(
        tasks, post_command, system_version=post_version, **common,
    )
    return PairedBenchmarkRun(baseline, post, compare_reports(baseline, post))


def report_to_json(report: SnapshotReport | TransferBenchmarkReport) -> str:
    return json.dumps(asdict(report), indent=2, sort_keys=True)
