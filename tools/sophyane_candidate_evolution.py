#!/usr/bin/env python3
"""Generate and objectively evaluate one constrained candidate patch."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from sophyane.evolution.candidate_evolution import (
    CandidateEvolver,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Recurrent principle → candidate diff → "
            "worktree → replay → regression → held-out gate"
        )
    )

    parser.add_argument(
        "--component",
        choices=(
            "python",
            "filesystem",
            "html",
            "shell",
            "semantic_router",
            "security",
        ),
        default="",
    )
    parser.add_argument(
        "--representatives",
        type=int,
        default=3,
    )
    parser.add_argument(
        "--commit-candidate",
        action="store_true",
        help=(
            "Commit a passing candidate on its evolution/* branch. "
            "This still does not merge or push main."
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List recurrent principles and exit.",
    )

    args = parser.parse_args()

    evolver = CandidateEvolver(
        Path.cwd()
    )

    if args.list:
        for item in (
            evolver.recurrent_principles()
        ):
            print()
            print(
                "Component:",
                item["component"],
            )
            print(
                "Distinct tasks:",
                len(
                    item.get(
                        "distinct_tasks",
                        [],
                    )
                ),
            )
            print(
                "Confidence:",
                item.get(
                    "maximum_confidence"
                ),
            )
            print(
                "Principle:",
                item["principle"],
            )

        return 0

    if not evolver.cloud_available():
        print(
            "ERROR: Gemini is unavailable. "
            "Candidate generation requires the cloud analyst."
        )
        return 2

    try:
        result = evolver.evolve(
            component=args.component,
            representative_limit=max(
                1,
                args.representatives,
            ),
            commit_candidate=(
                args.commit_candidate
            ),
        )
    except Exception as error:
        print()
        print("=" * 72)
        print("CANDIDATE GENERATION OR EVALUATION FAILED")
        print("=" * 72)
        print(
            f"{type(error).__name__}: {error}"
        )
        print("Candidate objectively evaluated: False")
        print("Candidate rejected by gates: False")
        print("Main modified: False")
        print("Main merged: False")
        print("Remote pushed: False")
        return 2

    print()
    print("=" * 72)
    print("CANDIDATE EVOLUTION RESULT")
    print("=" * 72)
    print("Candidate:", result.candidate_id)
    print("Component:", result.component)
    print("Branch:", result.branch)
    print("Worktree:", result.worktree)
    print(
        "Baseline representative score:",
        result.baseline_score,
    )
    print(
        "Candidate representative score:",
        result.candidate_score,
    )
    print(
        "Representative improved:",
        result.representative_improved,
    )
    print(
        "Targeted tests passed:",
        result.targeted_tests_passed,
    )
    print(
        "Full suite passed:",
        result.full_suite_passed,
    )
    print(
        "Held-out baseline score:",
        result.held_out_baseline_score,
    )
    print(
        "Held-out candidate score:",
        result.held_out_candidate_score,
    )
    print(
        "Held-out not regressed:",
        result.held_out_not_regressed,
    )
    print(
        "Security gate passed:",
        result.security_gate_passed,
    )
    print("Promotable:", result.promotable)
    print("Committed:", result.committed)
    print("Status:", result.status)
    print("Main modified: False")
    print("Main merged: False")
    print("Remote pushed: False")

    report = (
        Path.cwd()
        / ".sophyane-evolution"
        / "candidates"
        / f"{result.candidate_id}.json"
    )

    print("Report:", report)

    return (
        0
        if result.promotable
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
