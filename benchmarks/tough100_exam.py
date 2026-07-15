#!/usr/bin/env python3
"""Run 100 tough harness/coding questions against Sophyane and score replies."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from sophyane.expert.exam import run_exam


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description="Sophyane tough 100 exam")
    p.add_argument("--mode", choices=["expert", "llm", "hybrid"], default="hybrid")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--expert-only", action="store_true")
    args = p.parse_args()
    mode = "expert" if args.expert_only else args.mode
    report = run_exam(mode=mode, limit=args.limit, with_llm=mode != "expert")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "ok",
                    "version",
                    "mode",
                    "total",
                    "passed",
                    "pass_rate",
                    "avg_score",
                    "elapsed_sec",
                    "by_category",
                    "failures",
                )
            },
            indent=2,
        )
    )
    return 0 if report["pass_rate"] >= 80 else 1


if __name__ == "__main__":
    raise SystemExit(main())
