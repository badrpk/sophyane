"""Command-line interface for Sophyane Learning Intelligence."""
from __future__ import annotations

import argparse
import json

from sophyane import sli


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect Sophyane Learning Intelligence")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("learning-stats")
    recommend = sub.add_parser("recommend")
    recommend.add_argument("request")
    recommend.add_argument("--limit", type=int, default=5)
    trace = sub.add_parser("trace")
    trace.add_argument("--limit", type=int, default=10)
    args = parser.parse_args(argv)
    command = args.command or "learning-stats"

    with sli.connect() as db:
        if command == "learning-stats":
            data = sli.stats(db)
            print("SLI automatic learning statistics")
            print(f"  Database: {data['database']}")
            print(f"  Learned executions: {data['learned_executions']}")
            print(f"  Distinct actions: {data['distinct_actions']}")
            print(f"  Positive outcomes: {data['positive_outcomes']}")
            print(f"  Negative outcomes: {data['negative_outcomes']}")
            print(f"  Average reward: {data['average_reward']:+.3f}")
            print(f"  Average elapsed: {data['average_elapsed']:.3f}s")
            if data["sources"]:
                print("  Sources:")
                for source, count in sorted(data["sources"].items()):
                    print(f"    {source:<16} {count}")
            return 0

        if command == "recommend":
            rows = sli.recommend_actions(db, request=args.request, limit=args.limit)
            for index, item in enumerate(rows, 1):
                print(
                    f"{index}. {item['action']} confidence={item['confidence']:.3f} "
                    f"source={item['best_source']} attempts={item['attempts']}"
                )
            return 0

        rows = db.execute(
            "SELECT * FROM learned_execution_traces ORDER BY created_at DESC LIMIT ?",
            (max(1, args.limit),),
        ).fetchall()
        for row in rows:
            print(json.dumps(dict(row), ensure_ascii=False, indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
