"""Service health checks."""
from __future__ import annotations

import http.client
import socket

from .manifest import HealthCheck


def check_tcp(
    host: str,
    port: int,
    timeout: float,
) -> tuple[bool, str]:
    try:
        with socket.create_connection(
            (
                host,
                port,
            ),
            timeout=timeout,
        ):
            return (
                True,
                "tcp-connect-ok",
            )

    except OSError as error:
        return (
            False,
            f"{type(error).__name__}: {error}",
        )


def check_http(
    host: str,
    port: int,
    path: str,
    timeout: float,
) -> tuple[bool, str]:
    connection = http.client.HTTPConnection(
        host,
        port,
        timeout=timeout,
    )

    try:
        connection.request(
            "GET",
            path,
        )

        response = connection.getresponse()

        # Any actual HTTP response below server-error territory
        # proves the service endpoint is alive.
        ok = (
            200
            <= response.status
            < 500
        )

        return (
            ok,
            f"http-status={response.status}",
        )

    except OSError as error:
        return (
            False,
            f"{type(error).__name__}: {error}",
        )

    finally:
        connection.close()


def evaluate_health(
    health: HealthCheck,
    *,
    process_alive: bool,
) -> tuple[bool, str]:
    if health.kind == "process":
        return (
            process_alive,
            (
                "process-alive"
                if process_alive
                else "process-dead"
            ),
        )

    if not process_alive:
        return (
            False,
            "process-dead",
        )

    if health.kind == "tcp":
        return check_tcp(
            health.host,
            health.port,
            health.timeout_seconds,
        )

    if health.kind == "http":
        return check_http(
            health.host,
            health.port,
            health.path,
            health.timeout_seconds,
        )

    return (
        False,
        "unsupported-health-kind",
    )
