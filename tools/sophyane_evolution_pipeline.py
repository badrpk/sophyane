#!/usr/bin/env python3
"""Durable asynchronous Sophyane evolution pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sophyane.evolution import (
    EvolutionConfig,
    EvolutionEngine,
)
from sophyane.evolution.evidence_pipeline import (
    AnalysisPipeline,
    EvidenceStore,
)


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "stage",
        choices=(
            "collect",
            "analyze",
            "all",
            "status",
            "principles",
        ),
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=1,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
    )
    parser.add_argument(
        "--no-local",
        action="store_true",
    )
    parser.add_argument(
        "--no-cloud",
        action="store_true",
    )

    args = parser.parse_args()
    repo = Path.cwd().resolve()

    store = EvidenceStore(repo)

    if args.stage in {"collect", "all"}:
        config = EvolutionConfig(
            repo=repo,
            cycles=max(1, args.cycles),
            allow_cloud_analysis=False,
            allow_candidate_patches=False,
            allow_promotion=False,
        )

        EvolutionEngine(config).run()

    if args.stage in {"analyze", "all"}:
        pipeline = AnalysisPipeline(repo)

        results = pipeline.analyze_pending(
            limit=max(0, args.limit),
            use_local=not args.no_local,
            use_cloud=not args.no_cloud,
        )

        print(
            f"Analyzed evidence records: {len(results)}"
        )

    if args.stage == "status":
        print(
            json.dumps(
                store.status(),
                indent=2,
            )
        )

        pipeline = AnalysisPipeline(repo)

        print(
            "Local analyst available:",
            pipeline.local.available(),
        )
        print(
            "Cloud analyst available:",
            pipeline.cloud.available(),
        )

    if args.stage == "principles":
        data = store.principles._load()

        print(
            json.dumps(
                data,
                indent=2,
                ensure_ascii=False,
            )
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
