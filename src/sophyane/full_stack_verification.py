"""Mechanical verification for generated full-stack applications.

This module owns deterministic runtime verification after generated syntax
and automated tests have passed.

Generated service lifecycle is delegated exclusively to Sophyane Service
Fabric. No alternate background-process ownership is allowed here.
"""
from __future__ import annotations

import http.client
import time
from pathlib import Path
from typing import Callable

from sophyane.full_stack_runtime import (
    discover_service_manifest,
)
from sophyane.full_stack_scenarios import (
    discover_api_scenarios,
    scenario_summary,
)
from sophyane.service_fabric.supervisor import (
    ServiceSupervisor,
)


Progress = Callable[[str], None]


def verify_full_stack_application(
    workspace: Path,
    progress: Progress | None = None,
) -> tuple[bool, str]:
    """Verify one generated full-stack application mechanically.

    Verification currently proves:

    - generated runtime discovery succeeds;
    - Service Fabric owns process startup and teardown;
    - the generated service becomes healthy;
    - the configured frontend health path responds successfully;
    - every grounded, static GET API endpoint responds successfully;
    - non-GET endpoint contracts are preserved as evidence without
      fabricating request bodies.

    Mutation behavior remains the responsibility of the generated project's
    own automated tests until a future grounded mutation scenario is available.
    """
    progress = progress or (
        lambda _message:
            None
    )

    try:
        runtime, manifest = (
            discover_service_manifest(
                workspace,
                name="generated-full-stack",
            )
        )

    except Exception as error:
        return (
            False,
            "Service Fabric runtime discovery failed: "
            f"{type(error).__name__}: {error}",
        )

    endpoints = tuple(
        runtime.api_endpoints
    )

    if not endpoints:
        return (
            False,
            "Generated full-stack application exposed no "
            "grounded API endpoint contract.",
        )

    supervisor = ServiceSupervisor(
        workspace=workspace,
        progress=progress,
    )

    # SOPHYANE_FULL_STACK_BACKEND_SEMANTIC_HANDOFF_V2
    #
    # Runtime discovery has already grounded the actual generated service
    # entrypoint. Validate that source before starting the service so a
    # syntactically valid but architecturally unsafe backend cannot advance
    # to mechanical acceptance.
    entrypoint_path = (
        workspace
        / runtime.entrypoint
    ).resolve()

    workspace_root = (
        workspace.resolve()
    )

    if (
        entrypoint_path != workspace_root
        and workspace_root not in entrypoint_path.parents
    ):
        return (
            False,
            "Generated backend semantic validation rejected "
            "entrypoint outside workspace: "
            f"{runtime.entrypoint}",
        )

    if not entrypoint_path.is_file():
        return (
            False,
            "Generated backend semantic validation could not "
            "read runtime entrypoint: "
            f"{runtime.entrypoint}",
        )

    try:
        backend_source = entrypoint_path.read_text(
            encoding="utf-8",
        )
    except OSError as error:
        return (
            False,
            "Generated backend semantic validation failed to "
            "read runtime entrypoint: "
            f"{type(error).__name__}: {error}",
        )

    semantic_defects = (
        detect_backend_semantic_defects(
            backend_source
        )
    )

    if semantic_defects:
        return (
            False,
            "Generated backend semantic validation failed: "
            + ", ".join(
                semantic_defects
            ),
        )

    progress(
        "Full-stack backend semantic validation passed: "
        + runtime.entrypoint
    )

    evidence: list[str] = [
        f"entrypoint={runtime.entrypoint}",
        "backend_semantics=passed",
        f"base_url={runtime.base_url}",
        (
            "api_endpoints="
            + ", ".join(
                f"{endpoint.method} {endpoint.path}"
                for endpoint in endpoints
            )
        ),
    ]

    def request(
        method: str,
        path: str,
        body: object | None = None,
    ) -> tuple[
        int,
        str,
        bytes,
    ]:
        import json

        connection = (
            http.client.HTTPConnection(
                runtime.host,
                runtime.port,
                timeout=3,
            )
        )

        encoded: bytes | None = None

        headers: dict[
            str,
            str,
        ] = {}

        if body is not None:
            encoded = json.dumps(
                body,
                ensure_ascii=False,
            ).encode(
                "utf-8"
            )

            headers[
                "Content-Type"
            ] = "application/json"

        try:
            connection.request(
                method,
                path,
                body=encoded,
                headers=headers,
            )

            response = (
                connection.getresponse()
            )

            response_body = response.read(
                4096
            )

            return (
                int(
                    response.status
                ),
                str(
                    response.getheader(
                        "Content-Type",
                        "",
                    )
                ),
                response_body,
            )

        finally:
            connection.close()

    try:
        started = (
            supervisor.start_manifest(
                manifest
            )
        )

        if not started:
            return (
                False,
                "Service Fabric started no generated services.",
            )

        evidence.append(
            "pid="
            + str(
                started[
                    0
                ].process.pid
            )
        )

        deadline = (
            time.monotonic()
            + 6.0
        )

        last_status: list[
            dict[str, object]
        ] = []

        while (
            time.monotonic()
            < deadline
        ):
            last_status = (
                supervisor.status()
            )

            if (
                len(
                    last_status
                )
                == 1
                and last_status[
                    0
                ].get(
                    "alive"
                )
                is True
                and last_status[
                    0
                ].get(
                    "healthy"
                )
                is True
            ):
                break

            if (
                last_status
                and last_status[
                    0
                ].get(
                    "alive"
                )
                is False
            ):
                return (
                    False,
                    "Generated service exited before "
                    "becoming healthy: "
                    + repr(
                        last_status[
                            0
                        ]
                    ),
                )

            time.sleep(
                0.1
            )

        else:
            return (
                False,
                "Generated service did not become healthy: "
                + repr(
                    last_status
                ),
            )

        status = (
            last_status[
                0
            ]
        )

        evidence.append(
            "health="
            + str(
                status.get(
                    "health"
                )
            )
        )

        (
            frontend_status,
            frontend_type,
            frontend_body,
        ) = request(
            "GET",
            runtime.health_path,
        )

        frontend_bytes = len(
            frontend_body
        )

        if not (
            200
            <= frontend_status
            < 400
        ):
            return (
                False,
                "Frontend HTTP verification failed: "
                f"{runtime.health_path} -> "
                f"HTTP {frontend_status}",
            )

        evidence.append(
            "frontend="
            f"GET {runtime.health_path} "
            f"status={frontend_status} "
            f"content_type={frontend_type!r} "
            f"bytes_sampled={frontend_bytes}"
        )

        get_endpoints = tuple(
            endpoint
            for endpoint
            in endpoints
            if (
                endpoint.method
                == "GET"
                and "{"
                not in endpoint.path
                and "}"
                not in endpoint.path
            )
        )

        for endpoint in (
            get_endpoints
        ):
            (
                status_code,
                content_type,
                response_body,
            ) = request(
                "GET",
                endpoint.path,
            )

            bytes_sampled = len(
                response_body
            )

            if not (
                200
                <= status_code
                < 400
            ):
                return (
                    False,
                    "Grounded API verification failed: "
                    f"GET {endpoint.path} -> "
                    f"HTTP {status_code}",
                )

            evidence.append(
                "api="
                f"GET {endpoint.path} "
                f"status={status_code} "
                f"content_type={content_type!r} "
                f"bytes_sampled={bytes_sampled}"
            )

        mutation_endpoints = tuple(
            endpoint
            for endpoint
            in endpoints
            if (
                endpoint.method
                != "GET"
            )
        )

        scenarios = discover_api_scenarios(
            workspace
        )

        if scenarios:
            evidence.append(
                "grounded_scenarios="
                + " | ".join(
                    scenario_summary(
                        scenario
                    )
                    for scenario
                    in scenarios
                )
            )

        executed_mutations: set[
            tuple[str, str]
        ] = set()

        import json
        import re

        for scenario in scenarios:
            bound_values: dict[
                str,
                object,
            ] = {}

            for step in scenario.steps:
                # Ordinary GET endpoints are already verified through the
                # runtime endpoint contract above. A scenario GET is executed
                # here only when later scenario dataflow depends on its
                # response, or when it contains a path binding that must be
                # resolved as part of the scenario.
                if (
                    step.method == "GET"
                    and not step.bindings
                    and "{"
                    not in step.path
                    and "}"
                    not in step.path
                ):
                    continue

                resolved_path = step.path

                placeholders = re.findall(
                    r"\{([A-Za-z_][A-Za-z0-9_]*)\}",
                    resolved_path,
                )

                for name in placeholders:
                    if name not in bound_values:
                        return (
                            False,
                            "Grounded scenario binding unavailable: "
                            f"{name!r} required by "
                            f"{step.method} {step.path}; "
                            f"scenario={scenario.name}",
                        )

                    value = bound_values[
                        name
                    ]

                    if not isinstance(
                        value,
                        (
                            str,
                            int,
                        ),
                    ):
                        return (
                            False,
                            "Grounded scenario binding rejected: "
                            f"{name!r} has unsupported type "
                            f"{type(value).__name__}; "
                            f"scenario={scenario.name}",
                        )

                    resolved_path = (
                        resolved_path.replace(
                            "{"
                            + name
                            + "}",
                            str(
                                value
                            ),
                        )
                    )

                status_code, content_type, response_body = (
                    request(
                        step.method,
                        resolved_path,
                        step.body,
                    )
                )

                if step.expected_status:
                    accepted = (
                        status_code
                        in step.expected_status
                    )

                else:
                    accepted = (
                        200
                        <= status_code
                        < 400
                    )

                if not accepted:
                    return (
                        False,
                        "Grounded mutation verification failed: "
                        f"{step.method} {resolved_path} -> "
                        f"HTTP {status_code}; "
                        f"expected={step.expected_status or '2xx/3xx'}; "
                        f"scenario={scenario.name}",
                    )

                if step.method != "GET":
                    executed_mutations.add(
                        (
                            step.method,
                            step.path,
                        )
                    )

                evidence.append(
                    "scenario_api="
                    f"{step.method} {resolved_path} "
                    f"status={status_code} "
                    f"content_type={content_type!r} "
                    f"bytes_sampled={len(response_body)} "
                    f"scenario={scenario.name}"
                )

                if step.bindings:
                    try:
                        payload = json.loads(
                            response_body.decode(
                                "utf-8"
                            )
                        )

                    except (
                        UnicodeDecodeError,
                        json.JSONDecodeError,
                    ) as error:
                        return (
                            False,
                            "Grounded scenario response binding failed: "
                            "response bindings require JSON object; "
                            f"{type(error).__name__}: {error}",
                        )

                    if not isinstance(
                        payload,
                        dict,
                    ):
                        return (
                            False,
                            "Grounded scenario response binding failed: "
                            "response JSON is not an object.",
                        )

                    resolved_bindings: dict[
                        str,
                        object,
                    ] = {}

                    # Resolve all required fields first so one response step is
                    # bound atomically. A missing/invalid field cannot leave a
                    # partially-grounded scenario state behind.
                    for binding in step.bindings:
                        if binding.field not in payload:
                            return (
                                False,
                                "Grounded scenario response binding failed: "
                                f"field {binding.field!r} absent; "
                                f"binding={binding.name}",
                            )

                        value = payload[
                            binding.field
                        ]

                        if not isinstance(
                            value,
                            (
                                str,
                                int,
                            ),
                        ):
                            return (
                                False,
                                "Grounded scenario response binding failed: "
                                f"field {binding.field!r} has unsupported "
                                f"type {type(value).__name__}",
                            )

                        resolved_bindings[
                            binding.name
                        ] = value

                    bound_values.update(
                        resolved_bindings
                    )

                    for binding in step.bindings:
                        evidence.append(
                            "scenario_bind="
                            f"{binding.name}<-response."
                            f"{binding.field} "
                            f"scenario={scenario.name}"
                        )

        uncovered_mutations = tuple(
            endpoint
            for endpoint
            in mutation_endpoints
            if (
                endpoint.method,
                endpoint.path,
            )
            not in executed_mutations
        )

        if uncovered_mutations:
            evidence.append(
                "mutation_contracts_unexecuted="
                + ", ".join(
                    f"{endpoint.method} "
                    f"{endpoint.path}"
                    for endpoint
                    in uncovered_mutations
                )
                + " "
                "(no grounded static request scenario)"
            )

        return (
            True,
            "\n".join(
                evidence
            ),
        )

    except Exception as error:
        return (
            False,
            "\n".join(
                evidence
                + [
                    "Service Fabric verification exception: "
                    f"{type(error).__name__}: {error}"
                ]
            ),
        )

    finally:
        supervisor.stop_all()


__all__ = [
    "detect_backend_semantic_defects",
    "verify_full_stack_application",
]


def detect_backend_semantic_defects(
    source: str,
) -> tuple[str, ...]:
    """Return deterministic defects in a stdlib full-stack backend.

    SOPHYANE_FULL_STACK_BACKEND_SEMANTIC_GATE_V1

    This validator intentionally checks architectural invariants that
    Python syntax validation cannot prove.

    It remains generic: it does not depend on a task-management domain.
    """

    defects: list[str] = []

    text = str(
        source
        or ""
    )

    if not text.strip():
        return (
            "backend_source_missing",
        )

    # A threaded HTTP server must not share one module-global sqlite
    # cursor/connection across request threads.
    threaded_http = (
        "ThreadingHTTPServer"
        in text
    )

    sqlite_used = (
        "sqlite3"
        in text
    )

    if (
        threaded_http
        and sqlite_used
    ):
        connection_calls = text.count(
            "sqlite3.connect("
        )

        has_connection_factory = any(
            marker
            in text
            for marker in (
                "def get_db(",
                "def _get_db(",
                "def db_connection(",
                "def _db_connection(",
                "def connect_db(",
                "def _connect_db(",
            )
        )

        module_global_connection = (
            connection_calls == 1
            and any(
                marker
                in text
                for marker in (
                    "conn = sqlite3.connect(",
                    "connection = sqlite3.connect(",
                    "db = sqlite3.connect(",
                )
            )
        )

        if (
            module_global_connection
            and not has_connection_factory
        ):
            defects.append(
                "threaded_server_uses_shared_sqlite_connection"
            )

    # Full-stack JSON APIs require JSON-shaped client errors rather than
    # BaseHTTPRequestHandler.send_error(), which emits HTML.
    api_surface = (
        "/api/"
        in text
    )

    if api_surface:
        has_json_response_helper = any(
            marker
            in text
            for marker in (
                "def send_json(",
                "def _send_json(",
                "def json_response(",
                "def _json_response(",
                "def write_json(",
                "def _write_json(",
            )
        )

        has_json_error_object = any(
            marker
            in text
            for marker in (
                '"error":',
                "'error':",
                '"errors":',
                "'errors':",
            )
        )

        uses_html_send_error = (
            "send_error("
            in text
        )

        if (
            uses_html_send_error
            and not (
                has_json_response_helper
                or has_json_error_object
            )
        ):
            defects.append(
                "api_errors_are_not_structured_json"
            )

    # SQLite persistence requests require explicit deterministic schema
    # initialization.
    if (
        sqlite_used
        and "CREATE TABLE"
        not in text.upper()
    ):
        defects.append(
            "sqlite_schema_initialization_missing"
        )

    # When an API implements modification operations, malformed JSON must
    # have an explicit error path rather than escaping as an exception.
    mutating_handler = any(
        marker
        in text
        for marker in (
            "def do_POST(",
            "def do_PUT(",
            "def do_PATCH(",
        )
    )

    if mutating_handler:
        parses_json = (
            "json.loads("
            in text
        )

        catches_json_decode = any(
            marker
            in text
            for marker in (
                "JSONDecodeError",
                "except ValueError",
                "except json.JSONDecodeError",
            )
        )

        if (
            parses_json
            and not catches_json_decode
        ):
            defects.append(
                "malformed_json_request_not_handled"
            )

    return tuple(
        dict.fromkeys(
            defects
        )
    )
