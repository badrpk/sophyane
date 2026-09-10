"""Command-line entrypoint for explicit Sophyane discovery episodes."""
from __future__ import annotations

import argparse
import json

from pathlib import Path

from sophyane.discovery_engine import (
    run_discovery,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="sophyane-discovery",
    )

    parser.add_argument(
        "objective",
    )

    parser.add_argument(
        "--workspace",
        default=".",
    )

    parser.add_argument(
        "--hypotheses",
        type=int,
        default=3,
    )

    parser.add_argument(
        "--novelty-threshold",
        type=float,
        default=0.35,
    )

    args = parser.parse_args()

    episode = run_discovery(
        args.objective,
        workspace=Path(
            args.workspace
        ),
        hypothesis_limit=max(
            1,
            min(
                12,
                int(
                    args.hypotheses
                ),
            ),
        ),
        novelty_threshold=max(
            0.0,
            min(
                1.0,
                float(
                    args.novelty_threshold
                ),
            ),
        ),
    )

    print(
        json.dumps(
            episode.to_dict(),
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
