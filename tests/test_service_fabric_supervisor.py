import json
from pathlib import Path
import sys
import time

from sophyane.service_fabric.manifest import (
    load_manifest,
)
from sophyane.service_fabric.supervisor import (
    ServiceSupervisor,
)


def test_supervisor_starts_health_checks_and_stops(
    tmp_path: Path,
) -> None:
    manifest_path = (
        tmp_path
        / "service.json"
    )

    manifest_path.write_text(
        json.dumps(
            {
                "name":
                    "test-stack",

                "services":
                    [
                        {
                            "name":
                                "worker",

                            "command":
                                [
                                    sys.executable,
                                    "-c",
                                    (
                                        "import time;"
                                        "print('worker-ready', flush=True);"
                                        "time.sleep(20)"
                                    ),
                                ],

                            "health":
                                {
                                    "kind":
                                        "process",
                                },

                            "restart":
                                "no",
                        }
                    ],
            }
        ),
        encoding="utf-8",
    )

    manifest = load_manifest(
        manifest_path
    )

    supervisor = ServiceSupervisor(
        workspace=(
            tmp_path
            / "workspace"
        )
    )

    try:
        started = supervisor.start_manifest(
            manifest
        )

        assert len(
            started
        ) == 1

        time.sleep(
            0.1
        )

        status = supervisor.status()

        assert status[
            0
        ][
            "alive"
        ] is True

        assert status[
            0
        ][
            "healthy"
        ] is True

    finally:
        supervisor.stop_all()

    assert supervisor.running == {}


def test_reconcile_restarts_failed_service(
    tmp_path: Path,
) -> None:
    manifest_path = (
        tmp_path
        / "restart.json"
    )

    manifest_path.write_text(
        json.dumps(
            {
                "name":
                    "restart-stack",

                "services":
                    [
                        {
                            "name":
                                "failer",

                            "command":
                                [
                                    sys.executable,
                                    "-c",
                                    "raise SystemExit(3)",
                                ],

                            "restart":
                                "on-failure",
                        }
                    ],
            }
        ),
        encoding="utf-8",
    )

    manifest = load_manifest(
        manifest_path
    )

    supervisor = ServiceSupervisor(
        workspace=(
            tmp_path
            / "workspace"
        )
    )

    try:
        first = supervisor.start_manifest(
            manifest
        )[
            0
        ].process.pid

        time.sleep(
            0.15
        )

        supervisor.reconcile(
            manifest
        )

        second = supervisor.running[
            "failer"
        ].process.pid

        assert second != first

    finally:
        supervisor.stop_all()
