#!/usr/bin/env python3
"""Aggregate repeated comprehensive benchmark JSON files."""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


def nested(data: dict[str, Any], *keys: str) -> float:
    value: Any = data
    for key in keys:
        value = value[key]
    return float(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default="downloaded-results")
    parser.add_argument("--output", default="benchmark-results/aggregate")
    args = parser.parse_args()
    files = sorted(Path(args.root).rglob("results.json"))
    if not files:
        raise SystemExit("No results.json files found")

    runs = [json.loads(path.read_text(encoding="utf-8")) for path in files]
    metrics = {
        "large_dag_ratio": ("tests", "large_dag", "langgraph_to_sophyane_median_ratio"),
        "fan_out_ratio": ("tests", "fan_out_in", "langgraph_to_sophyane_median_ratio"),
        "sophyane_concurrency_wps": ("tests", "concurrency", "sophyane", "workflows_s"),
        "langgraph_concurrency_wps": ("tests", "concurrency", "langgraph", "workflows_s"),
        "sophyane_long_wps": ("tests", "long_running", "sophyane", "workflows_s"),
        "langgraph_long_wps": ("tests", "long_running", "langgraph", "workflows_s"),
        "sophyane_retained_per_iteration": ("tests", "memory_growth", "sophyane", "retained_per_iteration"),
        "langgraph_retained_per_iteration": ("tests", "memory_growth", "langgraph", "retained_per_iteration"),
    }
    summary: dict[str, Any] = {
        "run_count": len(runs),
        "profiles": sorted({str(run.get("profile")) for run in runs}),
        "platforms": sorted({str(run["environment"]["platform"]) for run in runs}),
        "metrics": {},
    }
    for name, path in metrics.items():
        values = [nested(run, *path) for run in runs]
        summary["metrics"][name] = {
            "median": statistics.median(values),
            "mean": statistics.fmean(values),
            "minimum": min(values),
            "maximum": max(values),
            "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
        }

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "aggregate.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = [
        "# Aggregated Sophyane v12 vs LangGraph benchmark",
        "",
        f"Independent runs aggregated: **{len(runs)}**",
        "",
        "All source `results.json` files are retained in the same GitHub Actions artifact.",
        "",
        "| Metric | Median | Mean | Min | Max | Std. dev. |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, values in summary["metrics"].items():
        lines.append(
            f"| {name} | {values['median']:.3f} | {values['mean']:.3f} | "
            f"{values['minimum']:.3f} | {values['maximum']:.3f} | {values['stdev']:.3f} |"
        )
    lines += [
        "",
        "## Scope",
        "",
        "These values describe local deterministic orchestration only. They do not compare hosted deployment, distributed queues, LangSmith, ecosystem maturity, or LLM quality.",
        "",
    ]
    (output / "AGGREGATE.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
