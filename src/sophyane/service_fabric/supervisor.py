"""Local process supervisor for Sophyane Service Fabric."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Callable

from .health import evaluate_health
from .manifest import (
    ServiceManifest,
    ServiceSpec,
)
from .state import save_state


Progress = Callable[[str], None]


@dataclass
class RunningService:
    spec: ServiceSpec
    process: subprocess.Popen
    log_path: Path
    started_at: float


class ServiceSupervisor:
    """Own local services without pretending they are kernel containers."""

    def __init__(
        self,
        *,
        workspace: Path | str,
        progress: Progress | None = None,
    ) -> None:
        self.workspace = Path(
            workspace
        ).resolve()

        self.workspace.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.progress = progress or (
            lambda _message:
                None
        )

        self.running: dict[
            str,
            RunningService,
        ] = {}

    def _order(
        self,
        manifest: ServiceManifest,
    ) -> list[ServiceSpec]:
        by_name = {
            item.name:
                item
            for item in manifest.services
        }

        result: list[
            ServiceSpec
        ] = []

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(
            name: str,
        ) -> None:
            if name in visited:
                return

            if name in visiting:
                raise ValueError(
                    "service dependency cycle"
                )

            visiting.add(
                name
            )

            service = by_name[
                name
            ]

            for dependency in service.depends_on:
                visit(
                    dependency
                )

            visiting.remove(
                name
            )

            visited.add(
                name
            )

            result.append(
                service
            )

        for service in manifest.services:
            visit(
                service.name
            )

        return result

    def start_service(
        self,
        spec: ServiceSpec,
    ) -> RunningService:
        existing = self.running.get(
            spec.name
        )

        if (
            existing is not None
            and existing.process.poll()
            is None
        ):
            return existing

        workdir = (
            self.workspace
            / spec.workdir
        ).resolve()

        try:
            workdir.relative_to(
                self.workspace
            )
        except ValueError as error:
            raise ValueError(
                f"service {spec.name}: workdir escapes workspace"
            ) from error

        workdir.mkdir(
            parents=True,
            exist_ok=True,
        )

        logs = (
            self.workspace
            / ".sophyane-service-logs"
        )

        logs.mkdir(
            parents=True,
            exist_ok=True,
        )

        log_path = (
            logs
            / f"{spec.name}.log"
        )

        log_file = log_path.open(
            "ab"
        )

        environment = {
            **os.environ,
            **spec.environment,
        }

        self.progress(
            "Service Fabric: starting "
            + spec.name
        )

        try:
            process = subprocess.Popen(
                list(
                    spec.command
                ),
                cwd=str(
                    workdir
                ),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

        except Exception:
            log_file.close()
            raise

        log_file.close()

        running = RunningService(
            spec=spec,
            process=process,
            log_path=log_path,
            started_at=time.time(),
        )

        self.running[
            spec.name
        ] = running

        return running

    def start_manifest(
        self,
        manifest: ServiceManifest,
    ) -> list[RunningService]:
        result = []

        for service in self._order(
            manifest
        ):
            result.append(
                self.start_service(
                    service
                )
            )

        self._persist(
            manifest
        )

        return result

    def stop_service(
        self,
        name: str,
        *,
        timeout: float = 5.0,
    ) -> bool:
        running = self.running.get(
            name
        )

        if running is None:
            return False

        process = running.process

        if process.poll() is not None:
            self.running.pop(
                name,
                None,
            )

            return True

        self.progress(
            "Service Fabric: stopping "
            + name
        )

        if (
            os.name == "posix"
            and hasattr(os, "killpg")
        ):
            try:
                os.killpg(
                    process.pid,
                    signal.SIGTERM,
                )

            except (
                ProcessLookupError,
                PermissionError,
            ):
                process.terminate()

        else:
            process.terminate()

        try:
            process.wait(
                timeout=timeout,
            )

        except subprocess.TimeoutExpired:
            if (
                os.name == "posix"
                and hasattr(os, "killpg")
            ):
                try:
                    os.killpg(
                        process.pid,
                        signal.SIGKILL,
                    )

                except (
                    ProcessLookupError,
                    PermissionError,
                ):
                    process.kill()

            else:
                process.kill()

            process.wait(
                timeout=2.0,
            )

        self.running.pop(
            name,
            None,
        )

        return True

    def stop_all(
        self,
    ) -> None:
        for name in list(
            self.running
        )[::-1]:
            self.stop_service(
                name
            )

    def status(
        self,
    ) -> list[dict[str, object]]:
        rows = []

        for name, running in self.running.items():
            alive = (
                running.process.poll()
                is None
            )

            healthy, health_detail = evaluate_health(
                running.spec.health,
                process_alive=alive,
            )

            rows.append(
                {
                    "name":
                        name,

                    "pid":
                        running.process.pid,

                    "alive":
                        alive,

                    "healthy":
                        healthy,

                    "health":
                        health_detail,

                    "restart":
                        running.spec.restart,

                    "log":
                        str(
                            running.log_path
                        ),

                    "published":
                        [
                            {
                                "protocol":
                                    item.protocol,

                                "local_port":
                                    item.local_port,

                                "public_port":
                                    item.public_port,

                                "hostname":
                                    item.hostname,

                                "tls":
                                    item.tls,
                            }
                            for item in running.spec.publish
                        ],
                }
            )

        return rows

    def reconcile(
        self,
        manifest: ServiceManifest,
    ) -> list[dict[str, object]]:
        desired = {
            item.name:
                item
            for item in manifest.services
        }

        for name in list(
            self.running
        ):
            if name not in desired:
                self.stop_service(
                    name
                )

        for service in self._order(
            manifest
        ):
            running = self.running.get(
                service.name
            )

            if running is None:
                self.start_service(
                    service
                )

                continue

            exit_code = (
                running.process.poll()
            )

            if exit_code is None:
                continue

            restart = (
                service.restart == "always"
                or (
                    service.restart
                    == "on-failure"
                    and exit_code != 0
                )
            )

            if restart:
                self.running.pop(
                    service.name,
                    None,
                )

                self.start_service(
                    service
                )

        self._persist(
            manifest
        )

        return self.status()

    def _persist(
        self,
        manifest: ServiceManifest,
    ) -> None:
        save_state(
            manifest.name,
            {
                "manifest":
                    manifest.name,

                "workspace":
                    str(
                        self.workspace
                    ),

                "services":
                    self.status(),
            },
        )
