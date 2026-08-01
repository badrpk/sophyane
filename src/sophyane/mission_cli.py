"""CLI for Sophyane durable missions."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from sophyane.mission_engine import (
    MissionStore,
    run_mission,
    run_mission_step,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sophyane-mission",
        description="Create and execute durable Sophyane missions.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("objective")
    create.add_argument(
        "--step",
        action="append",
        required=True,
        help="Repeat --step for each ordered mission action.",
    )
    create.add_argument(
        "--workspace",
        default=str(Path.cwd()),
    )

    run = subparsers.add_parser("run")
    run.add_argument("mission_id")
    run.add_argument("--max-iterations", type=int, default=50)

    tick = subparsers.add_parser("tick")
    tick.add_argument("mission_id")

    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("mission_id")

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--limit", type=int, default=20)

    return parser


def main() -> int:
    args = _parser().parse_args()
    store = MissionStore()

    if args.command == "create":
        mission = store.create(
            args.objective,
            args.step,
            workspace=args.workspace,
        )
        print(json.dumps(asdict(mission), indent=2))
        return 0

    if args.command == "run":
        result = run_mission(
            args.mission_id,
            store=store,
            max_iterations=args.max_iterations,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result.get("ok") else 1

    if args.command == "tick":
        result = run_mission_step(
            args.mission_id,
            store=store,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result.get("ok") else 1

    if args.command == "inspect":
        mission = store.get(args.mission_id)
        if mission is None:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": "mission_not_found",
                    },
                    indent=2,
                )
            )
            return 1

        print(
            json.dumps(
                {
                    "mission": asdict(mission),
                    "steps": [
                        asdict(step)
                        for step in store.steps(args.mission_id)
                    ],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "list":
        with store.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM missions
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (max(1, args.limit),),
            ).fetchall()

        print(
            json.dumps(
                [dict(row) for row in rows],
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
