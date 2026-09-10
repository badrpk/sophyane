from __future__ import annotations

import argparse
import json

from sophyane.cognitive_supervisor import (
    SupervisorConfig,
    clear_supervisor_stop,
    request_supervisor_stop,
    run_supervisor,
    supervisor_status,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="sophyane-cognitive-supervisor"
    )

    parser.add_argument(
        "objective",
        nargs="?",
        default="",
    )

    parser.add_argument(
        "--steps",
        type=int,
        default=8,
    )

    parser.add_argument(
        "--runtime",
        type=float,
        default=900.0,
    )

    parser.add_argument(
        "--status",
        action="store_true",
    )

    parser.add_argument(
        "--stop",
        action="store_true",
    )

    parser.add_argument(
        "--clear-stop",
        action="store_true",
    )

    args = parser.parse_args()

    config = SupervisorConfig(
        max_supervisor_steps=max(
            1,
            args.steps,
        ),
        max_runtime_seconds=max(
            1.0,
            args.runtime,
        ),
    )

    if args.stop:
        path = request_supervisor_stop(
            config=config
        )

        print(
            json.dumps(
                {
                    "stop_requested": True,
                    "path": str(path),
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        return 0

    if args.clear_stop:
        clear_supervisor_stop(
            config=config
        )

        print(
            json.dumps(
                {
                    "stop_requested": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        return 0

    if args.status:
        print(
            json.dumps(
                supervisor_status(
                    config=config
                ),
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

        return 0

    if not args.objective.strip():
        parser.error(
            "objective is required unless "
            "--status/--stop/--clear-stop is used"
        )

    result = run_supervisor(
        args.objective,
        config=config,
    )

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
