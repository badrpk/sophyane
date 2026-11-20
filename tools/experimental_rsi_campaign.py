#!/usr/bin/env python3
"""Autonomous, bounded experimental RSI campaign for the Termux ARM64 guest."""

from __future__ import annotations

import difflib
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import random
import shutil
import statistics
import subprocess
import tempfile
import time
from typing import Any

try:
    from . import experimental_rsi_cycle as guest_runner
except ImportError:  # executed directly as a script
    import experimental_rsi_cycle as guest_runner


ROOT = Path(__file__).resolve().parents[1]
TMP_ROOT = guest_runner.TMP_ROOT
AGENT = shutil.which("codex")
MINIMUM_IMPROVEMENT = 0.05
SAMPLE_COUNT = 7
BOOTSTRAP_RESAMPLES = 4000
MAX_CYCLES = 3
MAX_ATTEMPTS_PER_CYCLE = 2
MAX_TOTAL_GUEST_RUNS = MAX_CYCLES * (1 + MAX_ATTEMPTS_PER_CYCLE)
MAX_CAMPAIGN_BYTES = 512 * 1024 * 1024
AGENT_TIMEOUT_SECONDS = 240


def assess_samples(baseline: list[float], candidate: list[float], *, minimum_improvement: float) -> dict:
    """Require a median threshold gain plus a stable paired bootstrap signal."""
    if len(baseline) != len(candidate) or len(baseline) < 5:
        raise ValueError("baseline and candidate require at least five paired benchmark samples")
    if not math.isfinite(minimum_improvement) or minimum_improvement < 0:
        raise ValueError("minimum_improvement must be finite and non-negative")
    if any(not math.isfinite(value) or value <= 0 for value in (*baseline, *candidate)):
        raise ValueError("benchmark samples must be finite and positive")
    improvements = [new / old - 1.0 for old, new in zip(baseline, candidate)]
    median = statistics.median(improvements)
    positive_pairs = sum(value > 0 for value in improvements)
    rng = random.Random(0)
    bootstrap_medians = [
        statistics.median(rng.choices(improvements, k=len(improvements)))
        for _ in range(BOOTSTRAP_RESAMPLES)
    ]
    bootstrap_medians.sort()
    lower = bootstrap_medians[int(0.05 * (BOOTSTRAP_RESAMPLES - 1))]
    return {
        "accepted": median >= minimum_improvement and positive_pairs >= len(improvements) - 1 and lower > 0,
        "paired_improvements": improvements,
        "median_improvement": median,
        "positive_pairs": positive_pairs,
        "bootstrap_confidence": 0.90,
        "bootstrap_lower_bound": lower,
        "minimum_improvement": minimum_improvement,
    }


def validate_candidate_files(baseline: dict[str, bytes], candidate: dict[str, bytes], *, target: str) -> dict[str, bytes]:
    """Require exactly one changed file, and require it to be the selected target."""
    normalized = PurePosixPath(target)
    if normalized.is_absolute() or ".." in normalized.parts:
        raise ValueError("candidate target path is unsafe")
    if set(candidate) != {target} or target not in baseline:
        raise ValueError("candidate may change only the target file")
    if not isinstance(candidate[target], bytes) or not candidate[target]:
        raise ValueError("candidate target content must be non-empty bytes")
    if candidate[target] == baseline[target]:
        raise ValueError("candidate did not modify its target")
    return candidate


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tree_digest(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name, payload in sorted(files.items()):
        name_bytes = name.encode("utf-8")
        digest.update(len(name_bytes).to_bytes(4, "big"))
        digest.update(name_bytes)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _codex_source(target: str, baseline: bytes, test_paths: tuple[str, ...], task: str,
                  feedback: str, run_root: Path, cycle: int, attempt: int) -> tuple[bytes, dict]:
    if not AGENT:
        raise RuntimeError("configured Codex CLI is unavailable")
    workspace = run_root / f"agent-cycle-{cycle}-attempt-{attempt}"
    source = workspace / target
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(baseline)
    test_copy_paths = []
    for relative in test_paths:
        test = workspace / relative
        test.parent.mkdir(parents=True, exist_ok=True)
        test.write_bytes((ROOT / relative).read_bytes())
        test_copy_paths.append(relative)
    schema_path = workspace / "agent-output.schema.json"
    schema_path.write_text(json.dumps({
        "type": "object",
        "properties": {"path": {"type": "string", "const": target}, "content": {"type": "string"}},
        "required": ["path", "content"],
        "additionalProperties": False,
    }), encoding="utf-8")
    output_path = workspace / "agent-output.json"
    prompt = f"""You are the configured Codex coding agent proposing one isolated experimental optimization.
Target: {target}
Task: {task}
Tests available for reading: {', '.join(test_copy_paths)}
Prior attempt feedback (empty on first attempt): {feedback[:3000]}

Return one complete replacement file in the required JSON schema. Preserve exact behavior,
public interfaces, and all policy/security checks. Change only the target file. Prefer a
measurable CPU or allocation reduction for the stated benchmark. Do not edit files, run
commands, execute code, access other repositories, use network tools, or make commits.
The supplied target and tests are the complete context. If no semantics-preserving
optimization is clear, return the unchanged file; the harness will reject it.

Current target source follows:
```python
{baseline.decode('utf-8')}
```
"""
    command = [
        AGENT, "exec", "--ephemeral", "--sandbox", "read-only",
        "--skip-git-repo-check", "--output-schema", str(schema_path),
        "--output-last-message", str(output_path), "--cd", str(workspace), prompt,
    ]
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=workspace,
        shell=False,
        check=False,
        timeout=AGENT_TIMEOUT_SECONDS,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    agent_log = workspace / "codex-agent.log"
    agent_log.write_text(completed.stdout[-20000:], encoding="utf-8")
    if completed.returncode != 0 or not output_path.is_file():
        raise RuntimeError(f"Codex generation failed (exit {completed.returncode}); see {agent_log}")
    response = json.loads(output_path.read_text(encoding="utf-8"))
    if response.get("path") != target or not isinstance(response.get("content"), str):
        raise RuntimeError("Codex returned an invalid target response")
    candidate = response["content"].encode("utf-8")
    if len(candidate) > 256 * 1024:
        raise RuntimeError("Codex candidate exceeds the 256 KiB per-file limit")
    compile(candidate, target, "exec")
    return candidate, {
        "provider": "codex_cli",
        "version": subprocess.run([AGENT, "--version"], check=True, capture_output=True,
                                   text=True, timeout=10).stdout.strip(),
        "exit_code": completed.returncode,
        "wall_seconds": time.monotonic() - started,
        "output_sha256": _sha(candidate),
        "log_sha256": _sha(agent_log.read_bytes()),
        "workspace": str(workspace),
    }


def _benchmark_source(spec: dict[str, Any]) -> bytes:
    return f'''import json
import os
import statistics
import sys
import time
import pytest

sys.path.insert(0, "/tmp/candidate/src")
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
test_exit = int(pytest.main(["-q", "-p", "no:cacheprovider", *{list(spec['tests'])!r}]))
if test_exit:
    raise SystemExit(test_exit)
{spec['benchmark_setup']}
samples = []
for _ in range({SAMPLE_COUNT}):
    workload = make_workload()
    start = time.perf_counter_ns()
    for _ in range({spec['calls_per_sample']}):
        workload()
    elapsed = (time.perf_counter_ns() - start) / 1_000_000_000
    samples.append({spec['calls_per_sample']} / elapsed)
print("EXPERIMENTAL_SCORE=" + json.dumps({{
    "metric": {spec['metric']!r},
    "calls_per_sample": {spec['calls_per_sample']},
    "samples": samples,
    "median_score": statistics.median(samples),
}}))
'''.encode("utf-8")


def _parse_guest_score(result: dict) -> list[float]:
    lines = [line for line in result["pytest_and_benchmark_output"].splitlines()
             if line.startswith("EXPERIMENTAL_SCORE=")]
    if len(lines) != 1:
        raise RuntimeError(f"guest {result['label']} did not emit one benchmark distribution")
    payload = json.loads(lines[0].split("=", 1)[1])
    samples = payload.get("samples")
    if payload.get("metric") is None or not isinstance(samples, list) or len(samples) != SAMPLE_COUNT:
        raise RuntimeError(f"guest {result['label']} benchmark distribution was malformed")
    return samples


def _specifications() -> tuple[dict[str, Any], ...]:
    return (
        {
            "name": "cache_immutable_command_result_digest",
            "target": "src/sophyane/rsi/models.py",
            "tests": ("tests/rsi/test_command_result_digest.py",),
            "packages": ("src/sophyane/__init__.py", "src/sophyane/version.py",
                         "src/sophyane/rsi/__init__.py", "src/sophyane/rsi/models.py"),
            "task": "Lazily cache the digest of immutable CommandResult output on first access; preserve construction cost and the dataclasses.asdict field shape, adding no dataclass field.",
            "metric": "command_result_digest_accesses_per_second",
            "calls_per_sample": 30000,
            "benchmark_setup": '''from sophyane.rsi.models import CommandResult
result = CommandResult(("python3", "check"), 0, "stable output" * 32)
def make_workload():
    return lambda: result.digest''',
        },
        {
            "name": "reduce_metrics_record_history_truncation_allocations",
            "target": "src/sophyane/rsi/metrics.py",
            "tests": ("tests/test_autonomous_metrics.py", "tests/rsi/test_experimental_rsi_metrics.py"),
            "packages": ("src/sophyane/__init__.py", "src/sophyane/version.py",
                         "src/sophyane/rsi/__init__.py", "src/sophyane/rsi/metrics.py"),
            "task": "Optimize RSIMetrics.record history trimming while preserving the exact 256 newest records and validation behavior.",
            "metric": "rsi_metric_records_per_second",
            "calls_per_sample": 1500,
            "benchmark_setup": '''from sophyane.rsi.metrics import RSIMetrics
def make_workload():
    metrics = RSIMetrics()
    metrics.measurements = [dict(version="seed", capability={"benchmark_success": 1.0}, meta={"diagnosis_success": 1.0}, accepted=False) for _ in range(256)]
    count = [0]
    def run():
        count[0] += 1
        value = float(count[0])
        metrics.record("v1", {"benchmark_success": value}, {"diagnosis_success": value}, False)
    return run''',
        },
        {
            "name": "short_circuit_metrics_level_to_recent_accepted_records",
            "target": "src/sophyane/rsi/metrics.py",
            "tests": ("tests/test_autonomous_metrics.py", "tests/rsi/test_experimental_rsi_metrics.py",
                      "tests/rsi/test_benchmark_comparison.py"),
            "packages": ("src/sophyane/__init__.py", "src/sophyane/version.py",
                         "src/sophyane/rsi/__init__.py", "src/sophyane/rsi/metrics.py",
                         "src/sophyane/rsi/models.py", "src/sophyane/rsi/weakness.py",
                         "src/sophyane/rsi/benchmark.py"),
            "task": "Compute RSIMetrics.level from only the most recent three accepted records without changing level semantics.",
            "metric": "rsi_metrics_level_reads_per_second",
            "calls_per_sample": 10000,
            "benchmark_setup": '''from sophyane.rsi.metrics import RSIMetrics
metrics = RSIMetrics()
metrics.measurements = [dict(version="v1", capability={"benchmark_success": float(i)}, meta={"diagnosis_success": float(i)}, accepted=True) for i in range(256)]
def make_workload():
    return lambda: metrics.level''',
        },
    )


def _source_bundle(spec: dict[str, Any], target_data: bytes, inherited: dict[str, bytes]) -> dict[str, bytes]:
    files = {
        "src/sophyane/__init__.py": (ROOT / "src/sophyane/__init__.py").read_bytes(),
        "src/sophyane/version.py": (ROOT / "src/sophyane/version.py").read_bytes(),
        "src/sophyane/rsi/__init__.py": (ROOT / "src/sophyane/rsi/__init__.py").read_bytes(),
    }
    for retained_path, retained_source in inherited.items():
        files[retained_path] = retained_source
    files[spec["target"]] = target_data
    for relative in spec["packages"]:
        files[relative] = target_data if relative == spec["target"] else (ROOT / relative).read_bytes()
    for relative in spec["tests"]:
        files[relative] = (ROOT / relative).read_bytes()
    files["experimental_check.py"] = _benchmark_source(spec)
    return files


def run_campaign(*, cycles: int = MAX_CYCLES) -> dict:
    if cycles != MAX_CYCLES:
        raise ValueError(f"the bounded campaign is fixed at exactly {MAX_CYCLES} cycles")
    if not AGENT:
        raise RuntimeError("configured Codex CLI is unavailable")
    guest_fingerprints = guest_runner._verify_assets()
    run_root = Path(tempfile.mkdtemp(prefix="sophyane-experimental-campaign-", dir=TMP_ROOT))
    specs = _specifications()
    reports = []
    inherited: dict[str, bytes] = {
        "src/sophyane/rsi/benchmark.py": (ROOT / "src/sophyane/rsi/benchmark.py").read_bytes(),
    }
    previous_retained_sha = _sha(inherited["src/sophyane/rsi/benchmark.py"])
    if previous_retained_sha != "8bb3ac96b7c7383bcd457f7dd2f1948a02ff1387bdcfd8b3e0397eb44e4fb799":
        raise RuntimeError("retained experimental starting candidate fingerprint mismatch")
    initial_retained_sha = previous_retained_sha
    guest_runs = 0

    for cycle_index, spec in enumerate(specs, start=1):
        baseline = (ROOT / spec["target"]).read_bytes()
        baseline_sha = _sha(baseline)
        baseline_bundle = _source_bundle(spec, baseline, inherited)
        baseline_bundle_digest = _tree_digest(baseline_bundle)
        initrd = guest_runner._prepare_initrd(run_root / f"initrd-cycle-{cycle_index}", tuple(baseline_bundle))
        if guest_runs >= MAX_TOTAL_GUEST_RUNS:
            raise RuntimeError("total guest run budget exceeded")
        baseline_result = guest_runner._run_guest(baseline_bundle, run_root, initrd, f"cycle-{cycle_index}-baseline")
        guest_runs += 1
        baseline_samples = _parse_guest_score(baseline_result)
        if guest_runner._directory_bytes(run_root) > MAX_CAMPAIGN_BYTES:
            raise RuntimeError("campaign scratch exceeded its 512 MiB limit")
        attempts = []
        retained = None
        feedback = ""

        for attempt_index in range(1, MAX_ATTEMPTS_PER_CYCLE + 1):
            try:
                proposed, agent_origin = _codex_source(
                    spec["target"], baseline, spec["tests"], spec["task"], feedback,
                    run_root, cycle_index, attempt_index,
                )
            except Exception as error:
                feedback = f"Codex generation error: {type(error).__name__}: {error}"
                attempts.append({"attempt": attempt_index, "origin": "codex_cli", "rejected": feedback})
                continue
            try:
                validate_candidate_files({spec["target"]: baseline}, {spec["target"]: proposed}, target=spec["target"])
            except ValueError as error:
                feedback = f"Candidate rejected by allowlist: {error}"
                attempts.append({"attempt": attempt_index, "rejected": feedback, "candidate_sha256": _sha(proposed)})
                continue
            candidate_bundle = _source_bundle(spec, proposed, inherited)
            guest_runs += 1
            candidate_diff = "".join(difflib.unified_diff(
                baseline.decode("utf-8").splitlines(keepends=True),
                proposed.decode("utf-8").splitlines(keepends=True),
                fromfile="baseline/" + spec["target"], tofile="candidate/" + spec["target"],
            ))
            try:
                if guest_runs > MAX_TOTAL_GUEST_RUNS:
                    raise RuntimeError("total guest run budget exceeded")
                candidate_result = guest_runner._run_guest(
                    candidate_bundle, run_root, initrd, f"cycle-{cycle_index}-candidate-{attempt_index}"
                )
            except Exception as error:
                feedback = f"Candidate guest verification failed: {type(error).__name__}: {error}"
                attempts.append({
                    "attempt": attempt_index,
                    "candidate_sha256": _sha(proposed),
                    "candidate_diff": candidate_diff,
                    "pytest_exit_code": None,
                    "benchmark_samples": [],
                    "rejected": feedback,
                })
                if guest_runner._directory_bytes(run_root) > MAX_CAMPAIGN_BYTES:
                    raise RuntimeError("campaign scratch exceeded its 512 MiB limit") from error
                continue
            if guest_runner._directory_bytes(run_root) > MAX_CAMPAIGN_BYTES:
                raise RuntimeError("campaign scratch exceeded its 512 MiB limit")
            candidate_samples = _parse_guest_score(candidate_result)
            assessment = assess_samples(baseline_samples, candidate_samples, minimum_improvement=MINIMUM_IMPROVEMENT)
            attempt_report = {
                "attempt": attempt_index,
                "origin": agent_origin,
                "candidate_sha256": _sha(proposed),
                "candidate_diff": candidate_diff,
                "pytest_output": candidate_result["pytest_and_benchmark_output"].split("EXPERIMENTAL_SCORE=", 1)[0],
                "pytest_exit_code": candidate_result["exit_code"],
                "benchmark_samples": candidate_samples,
                "assessment": assessment,
                "guest_evidence": candidate_result,
            }
            attempts.append(attempt_report)
            if assessment["accepted"]:
                retained = proposed
                break
            feedback = (
                f"The candidate passed its tests but the measured change did not pass the 5% threshold "
                f"and paired bootstrap rule. Assessment: {json.dumps(assessment)}. Propose a different "
                f"semantics-preserving optimization; do not weaken tests or change policy."
            )

        if retained is None:
            report = {
                "schema_version": 1,
                "track": "EXPERIMENTAL_RSI_ANDROID_TERMUX",
                "hardened_phase4_status": "UNCHANGED_AND_NOT_EVALUATED",
                "status": "STOPPED_NO_ACCEPTED_CANDIDATE",
                "completed_cycles": reports,
                "failed_cycle": spec["name"],
                "attempts": attempts,
                "baseline_source_sha256": baseline_sha,
                "baseline_bundle_sha256": baseline_bundle_digest,
                "baseline_benchmark_samples": baseline_samples,
                "baseline_guest_evidence": baseline_result,
                "guest_runs": guest_runs,
                "run_root": str(run_root),
                "guest_asset_sha256": guest_fingerprints,
            }
            (run_root / "experimental-rsi-report.json").write_text(json.dumps(report, indent=2, sort_keys=True))
            return report

        target_path = ROOT / spec["target"]
        if target_path.read_bytes() != baseline:
            raise RuntimeError("experimental target changed concurrently; refusing to retain candidate")
        prior_inherited = {path: _sha(data) for path, data in inherited.items()}
        target_path.write_bytes(retained)
        retained_sha = _sha(retained)
        inherited[spec["target"]] = retained
        report = {
            "cycle": cycle_index,
            "name": spec["name"],
            "target": spec["target"],
            "baseline_source_sha256": baseline_sha,
            "baseline_bundle_sha256": baseline_bundle_digest,
            "previous_cycle_retained_sha256": previous_retained_sha,
            "inherited_retained_files": prior_inherited,
            "baseline_benchmark_samples": baseline_samples,
            "baseline_guest_evidence": baseline_result,
            "attempts": attempts,
            "retained_source_sha256": retained_sha,
            "retained": True,
        }
        reports.append(report)
        previous_retained_sha = retained_sha

    campaign = {
        "schema_version": 1,
        "track": "EXPERIMENTAL_RSI_ANDROID_TERMUX",
        "hardened_phase4_status": "UNCHANGED_AND_NOT_EVALUATED",
        "status": "THREE_CONSECUTIVE_IMPROVEMENTS",
        "base_branch": "experimental/rsi-cycle-20261121",
        "starting_retained_candidate_sha256": initial_retained_sha,
        "completed_cycles": reports,
        "guest_runs": guest_runs,
        "guest_run_budget": MAX_TOTAL_GUEST_RUNS,
        "attempts_per_cycle_budget": MAX_ATTEMPTS_PER_CYCLE,
        "run_root": str(run_root),
        "guest_asset_sha256": guest_fingerprints,
    }
    (run_root / "experimental-rsi-report.json").write_text(json.dumps(campaign, indent=2, sort_keys=True))
    return campaign


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--execute-candidates", action="store_true")
    args = parser.parse_args()
    if not args.execute_candidates:
        print("EXPERIMENTAL_RSI_ABORT: candidate execution disabled; pass --execute-candidates")
        return 2
    try:
        report = run_campaign()
    except Exception as error:
        print(f"EXPERIMENTAL_RSI_ABORT: {type(error).__name__}: {error}")
        return 2
    print(json.dumps({
        "status": report["status"],
        "completed_cycles": len(report.get("completed_cycles", [])),
        "guest_runs": report["guest_runs"],
        "report": report["run_root"] + "/experimental-rsi-report.json",
    }, indent=2))
    return 0 if report["status"] == "THREE_CONSECUTIVE_IMPROVEMENTS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
