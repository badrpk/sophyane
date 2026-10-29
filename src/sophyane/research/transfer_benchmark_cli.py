"""CLI for paired RSI transfer benchmark runs."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import shlex
import sys

from sophyane.research.transfer_benchmark import (
    RunRecord,
    SnapshotReport,
    compare_reports,
    load_tasks_file,
    run_paired_benchmark,
    run_snapshot,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a frozen, isolated RSI transfer benchmark")
    parser.add_argument("--baseline-command", help="solver command; reads task JSON from stdin")
    parser.add_argument("--post-command", help="solver command; reads task JSON from stdin")
    parser.add_argument("--baseline-version")
    parser.add_argument("--post-version")
    parser.add_argument("--baseline-report", help="saved baseline snapshot JSON for --post-only")
    parser.add_argument("--baseline-only", action="store_true", help="run and save control before creating candidate")
    parser.add_argument("--post-only", action="store_true", help="evaluate candidate and compare with --baseline-report")
    parser.add_argument("--tasks-file", help="evaluator-only frozen JSON pack; never mount it in the solver root")
    parser.add_argument("--lean-command", help="Lean grader command; {workspace} and {source} are substituted")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--workspace-root", help="parent for fresh per-run workspaces")
    parser.add_argument("--holdout-attested", action="store_true", help="assert externally controlled holdout isolation")
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--output", help="write JSON report here; stdout otherwise")
    args = parser.parse_args(argv)
    try:
        if not args.tasks_file:
            parser.error("--tasks-file is required; built-in example tasks are not a blind holdout")
        tasks = load_tasks_file(args.tasks_file)
        lean_command = shlex.split(args.lean_command) if args.lean_command else None
        common = dict(
            repetitions=args.repetitions, timeout_seconds=args.timeout,
            workspace_root=args.workspace_root, holdout_attested=args.holdout_attested,
            seed=args.seed, lean_command=lean_command,
        )
        if args.baseline_only:
            if not args.baseline_command or not args.baseline_version or args.post_only or args.post_command:
                parser.error("--baseline-only requires --baseline-command and --baseline-version only")
            snapshot = run_snapshot(
                tasks, shlex.split(args.baseline_command), system_version=args.baseline_version, **common,
            )
            document = json.dumps(asdict(snapshot), indent=2, sort_keys=True)
        elif args.post_only:
            if not args.baseline_report or not args.post_command or not args.post_version or args.baseline_command:
                parser.error("--post-only requires --baseline-report, --post-command, and --post-version")
            raw = json.loads(open(args.baseline_report, encoding="utf-8").read())
            raw["runs"] = tuple(RunRecord(**item) for item in raw["runs"])
            baseline = SnapshotReport(**raw)
            post = run_snapshot(
                tasks, shlex.split(args.post_command), system_version=args.post_version, **common,
            )
            comparison = compare_reports(baseline, post)
            document = json.dumps({
                "baseline": asdict(baseline), "post": asdict(post), "comparison": asdict(comparison),
            }, indent=2, sort_keys=True)
        else:
            if not all((args.baseline_command, args.post_command, args.baseline_version, args.post_version)):
                parser.error("paired mode requires both commands and both version labels")
            result = run_paired_benchmark(
                tasks, shlex.split(args.baseline_command), shlex.split(args.post_command),
                baseline_version=args.baseline_version, post_version=args.post_version,
                **common,
            )
            document = json.dumps({
                "baseline": asdict(result.baseline),
                "post": asdict(result.post),
                "comparison": asdict(result.comparison),
            }, indent=2, sort_keys=True)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(document + "\n")
    else:
        sys.stdout.write(document + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
