#!/usr/bin/env python3
"""Run constrained Sophyane harness evolution."""

from __future__ import annotations

import argparse
from pathlib import Path

from sophyane.evolution import (
    EvolutionConfig,
    EvolutionEngine,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Local-task → SLI → validators → "
            "Gemini diagnosis → constrained candidate gate"
        )
    )

    parser.add_argument(
        "--cycles",
        type=int,
        default=1,
    )
    parser.add_argument(
        "--allow-patches",
        action="store_true",
        help=(
            "Allow Gemini to propose candidate patches. "
            "Patches still run only inside disposable worktrees."
        ),
    )
    parser.add_argument(
        "--promote",
        action="store_true",
        help=(
            "Commit a candidate branch after all gates pass. "
            "This never merges or pushes main automatically."
        ),
    )
    parser.add_argument(
        "--no-cloud",
        action="store_true",
    )

    args = parser.parse_args()

    repo = Path.cwd().resolve()

    config = EvolutionConfig(
        repo=repo,
        cycles=max(1, args.cycles),
        allow_cloud_analysis=(
            not args.no_cloud
        ),
        allow_candidate_patches=(
            args.allow_patches
        ),
        allow_promotion=args.promote,
    )

    records = EvolutionEngine(
        config
    ).run()

    passed = sum(
        1
        for record in records
        if record.validation.passed
    )

    promotable = sum(
        1
        for record in records
        if (
            record.gate
            and record.gate.promotable
        )
    )

    print()
    print(
        f"Cycles: {len(records)}"
    )
    print(
        f"SLI passes: {passed}"
    )
    print(
        f"Promotable candidates: {promotable}"
    )
    print(
        "Records: "
        + str(
            config.resolved_records_dir()
        )
    )
    print(
        "Main branch modified automatically: False"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
