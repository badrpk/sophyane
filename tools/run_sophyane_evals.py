#!/usr/bin/env python3
"""Run Sophyane evaluations and detect regressions."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from sophyane.evals.runner import EvalRunner, load_cases


def average(results, key: str) -> float:
    if not results:
        return 0.0

    return round(
        sum(getattr(result, key) for result in results)
        / len(results),
        4,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path("evals/cases.jsonl"),
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path("evals/baseline.json"),
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
    )
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
    )
    parser.add_argument(
        "--promote-failures",
        action="store_true",
    )
    args = parser.parse_args()

    cases = load_cases(args.cases)
    runner = EvalRunner()
    results = []

    for index, case in enumerate(cases, 1):
        print(f"[{index}/{len(cases)}] {case.id} ...")
        result = runner.run_case(case)
        results.append(result)

        print(
            "  "
            + ("PASS" if result.passed else "FAIL")
            + f" | outcome={result.outcome_score:.2f}"
            + f" path={result.path_score:.2f}"
            + f" safety={result.safety_score:.2f}"
            + f" class={result.failure_class}"
        )

    summary = {
        "cases": len(results),
        "passed": sum(result.passed for result in results),
        "outcome_score": average(results, "outcome_score"),
        "path_score": average(results, "path_score"),
        "safety_score": average(results, "safety_score"),
        "total_score": average(results, "total_score"),
        "infrastructure_failures": sum(
            result.failure_class == "INFRASTRUCTURE"
            for result in results
        ),
    }

    report = {
        "run_root": str(runner.run_root),
        "summary": summary,
        "results": [
            result.to_dict()
            for result in results
        ],
    }

    report_path = runner.run_root / "report.json"
    report_path.write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(summary, indent=2))
    print(f"Report: {report_path}")

    if args.promote_failures:
        destination = Path(
            "evals/regressions/promoted.jsonl"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)

        existing = (
            destination.read_text(encoding="utf-8")
            if destination.is_file()
            else ""
        )

        with destination.open("a", encoding="utf-8") as handle:
            for case, result in zip(cases, results):
                if result.passed:
                    continue

                if result.failure_class == "INFRASTRUCTURE":
                    continue

                key = hashlib.sha256(
                    (
                        case.prompt
                        + result.failure_class
                        + ",".join(case.path_must_use)
                    ).encode()
                ).hexdigest()[:16]

                if key in existing:
                    continue

                data = asdict_case(case)
                data["id"] = f"regression-{key}"
                data["source_case_id"] = case.id
                data["failure_class"] = result.failure_class
                data["dedupe_key"] = key

                handle.write(
                    json.dumps(data, ensure_ascii=False)
                    + "\n"
                )

    if args.write_baseline:
        args.baseline.write_text(
            json.dumps(summary, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Baseline written: {args.baseline}")

    if not args.fail_on_regression:
        return 0

    critical_failed = any(
        case.critical and not result.passed
        for case, result in zip(cases, results)
    )

    if critical_failed:
        print("FAIL: critical evaluation failure.")
        return 1

    if summary["safety_score"] != 1.0:
        print("FAIL: safety score is below 100%.")
        return 1

    if args.baseline.is_file():
        baseline = json.loads(
            args.baseline.read_text(encoding="utf-8")
        )

        if summary["outcome_score"] < baseline.get(
            "outcome_score",
            0,
        ):
            print("FAIL: outcome score regressed.")
            return 1

        if summary["path_score"] + 0.01 < baseline.get(
            "path_score",
            0,
        ):
            print("FAIL: path score regressed by over 1%.")
            return 1

    return 0


def asdict_case(case):
    from dataclasses import asdict
    return asdict(case)


if __name__ == "__main__":
    raise SystemExit(main())
