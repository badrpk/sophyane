"""CLI for Sophyane Service Fabric v1."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from sophyane.edge.routing import (
    routes_from_manifest,
)
from sophyane.service_fabric import (
    ServiceSupervisor,
    detect_host_capabilities,
    load_manifest,
)


def _json(
    payload,
) -> None:
    print(
        json.dumps(
            payload,
            indent=2,
            default=str,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="sophyane-service"
    )

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    sub.add_parser(
        "host"
    )

    validate = sub.add_parser(
        "validate"
    )

    validate.add_argument(
        "manifest"
    )

    routes = sub.add_parser(
        "routes"
    )

    routes.add_argument(
        "manifest"
    )

    run = sub.add_parser(
        "run"
    )

    run.add_argument(
        "manifest"
    )

    run.add_argument(
        "--workspace",
        default=".",
    )

    run.add_argument(
        "--seconds",
        type=float,
        default=0.0,
    )

    args = parser.parse_args()

    if args.command == "host":
        _json(
            detect_host_capabilities().__dict__
        )

        return 0

    manifest = load_manifest(
        args.manifest
    )

    if args.command == "validate":
        _json(
            {
                "ok":
                    True,

                "name":
                    manifest.name,

                "services":
                    [
                        service.name
                        for service in manifest.services
                    ],
            }
        )

        return 0

    if args.command == "routes":
        _json(
            [
                route.__dict__
                for route in routes_from_manifest(
                    manifest
                )
            ]
        )

        return 0

    supervisor = ServiceSupervisor(
        workspace=Path(
            args.workspace
        ),
        progress=lambda message:
            print(
                "PROGRESS:",
                message,
            ),
    )

    try:
        supervisor.start_manifest(
            manifest
        )

        if args.seconds > 0:
            deadline = (
                time.time()
                + args.seconds
            )

            while time.time() < deadline:
                time.sleep(
                    0.2
                )

                supervisor.reconcile(
                    manifest
                )

        _json(
            supervisor.status()
        )

        return 0

    finally:
        supervisor.stop_all()


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
