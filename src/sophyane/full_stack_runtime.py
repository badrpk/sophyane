"""Generic generated full-stack application runtime adaptation.

This module does not supervise processes itself.

It converts grounded evidence from a generated Python web project into the
existing Sophyane Service Fabric model.
"""
from __future__ import annotations

import ast
import os
import re
import socket
import sys
from dataclasses import dataclass
from pathlib import Path

from sophyane.service_fabric.manifest import (
    HealthCheck,
    ServiceManifest,
    ServiceSpec,
)


@dataclass(frozen=True)
class ApiEndpoint:
    method: str
    path: str
    source: str = ""


@dataclass(frozen=True)
class FullStackRuntime:
    entrypoint: str
    host: str
    port: int
    command: tuple[str, ...]
    environment: dict[str, str]
    health_path: str
    api_paths: tuple[str, ...]
    api_endpoints: tuple[ApiEndpoint, ...] = ()

    @property
    def base_url(self) -> str:
        return (
            f"http://{self.host}:{self.port}"
        )


_ENTRYPOINT_NAMES = (
    "backend/app.py",
    "backend/server.py",
    "backend/main.py",
    "app.py",
    "server.py",
    "main.py",
)

_SERVER_MARKERS = (
    "BaseHTTPRequestHandler",
    "ThreadingHTTPServer",
    "HTTPServer",
    "serve_forever",
)


def _inside(
    root: Path,
    candidate: Path,
) -> bool:
    try:
        candidate.resolve().relative_to(
            root.resolve()
        )
    except ValueError:
        return False

    return True


def python_sources(
    workspace: Path,
) -> list[Path]:
    root = workspace.resolve()

    values: list[Path] = []

    for path in root.rglob("*.py"):
        if not path.is_file():
            continue

        if not _inside(
            root,
            path,
        ):
            continue

        relative = path.relative_to(
            root
        )

        if any(
            part in {
                ".venv",
                "venv",
                "__pycache__",
            }
            for part in relative.parts
        ):
            continue

        values.append(path)

    return sorted(
        values,
        key=lambda item:
            item.relative_to(
                root
            ).as_posix(),
    )


def discover_entrypoint(
    workspace: Path,
) -> Path | None:
    root = workspace.resolve()

    for relative in _ENTRYPOINT_NAMES:
        candidate = root / relative

        if candidate.is_file():
            return candidate

    for candidate in python_sources(
        root
    ):
        source = candidate.read_text(
            encoding="utf-8",
            errors="ignore",
        )

        if all(
            marker in source
            for marker in (
                "http.server",
                "serve_forever",
            )
        ):
            return candidate

        if any(
            marker in source
            for marker in _SERVER_MARKERS
        ):
            return candidate

    return None


def _integer_assignments(
    source: str,
) -> dict[str, int]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}

    result: dict[str, int] = {}

    for node in tree.body:
        if not isinstance(
            node,
            (
                ast.Assign,
                ast.AnnAssign,
            ),
        ):
            continue

        targets = (
            node.targets
            if isinstance(
                node,
                ast.Assign,
            )
            else [node.target]
        )

        value = node.value

        if not isinstance(
            value,
            ast.Constant,
        ):
            continue

        if not isinstance(
            value.value,
            int,
        ):
            continue

        for target in targets:
            if not isinstance(
                target,
                ast.Name,
            ):
                continue

            result[
                target.id
            ] = int(
                value.value
            )

    return result


def discover_declared_port(
    entrypoint: Path,
) -> int | None:
    source = entrypoint.read_text(
        encoding="utf-8",
        errors="ignore",
    )

    # Strongest contract: generated project explicitly accepts PORT.
    if re.search(
        r'''os\.environ(?:\.get|\[).*?PORT''',
        source,
        flags=re.I | re.S,
    ):
        return None

    assignments = _integer_assignments(
        source
    )

    for name in (
        "PORT",
        "HTTP_PORT",
        "SERVER_PORT",
    ):
        port = assignments.get(
            name
        )

        if (
            port is not None
            and 1 <= port <= 65535
        ):
            return port

    patterns = (
        r'''(?:ThreadingHTTPServer|HTTPServer)
            \s*\(
            \s*\(
            \s*["'](?:127\.0\.0\.1|localhost)["']
            \s*,\s*
            (?P<port>[0-9]{2,5})
        ''',
        r'''server_address
            \s*=
            \s*\(
            \s*["'](?:127\.0\.0\.1|localhost)["']
            \s*,\s*
            (?P<port>[0-9]{2,5})
        ''',
    )

    for pattern in patterns:
        match = re.search(
            pattern,
            source,
            flags=(
                re.I
                | re.X
            ),
        )

        if match is None:
            continue

        port = int(
            match.group(
                "port"
            )
        )

        if 1 <= port <= 65535:
            return port

    return None


def choose_free_port(
    host: str = "127.0.0.1",
) -> int:
    with socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM,
    ) as probe:
        probe.bind(
            (
                host,
                0,
            )
        )

        return int(
            probe.getsockname()[1]
        )



def _api_literal(
    node: ast.AST,
) -> str | None:
    if not isinstance(
        node,
        ast.Constant,
    ):
        return None

    if not isinstance(
        node.value,
        str,
    ):
        return None

    value = node.value.strip()

    if not value.startswith(
        "/api/"
    ):
        return None

    return value


def _path_expression(
    node: ast.AST,
) -> bool:
    if isinstance(
        node,
        ast.Attribute,
    ):
        return (
            node.attr == "path"
        )

    if isinstance(
        node,
        ast.Name,
    ):
        return (
            node.id.casefold()
            in {
                "path",
                "route",
                "request_path",
                "request_route",
            }
        )

    if isinstance(
        node,
        ast.Call,
    ):
        if isinstance(
            node.func,
            ast.Attribute,
        ):
            if (
                node.func.attr
                in {
                    "split",
                    "rstrip",
                    "strip",
                }
            ):
                return _path_expression(
                    node.func.value
                )

    if isinstance(
        node,
        ast.Subscript,
    ):
        return _path_expression(
            node.value
        )

    return False


def _comparison_routes(
    node: ast.Compare,
) -> set[str]:
    values: set[str] = set()

    operands = [
        node.left,
        *node.comparators,
    ]

    if not any(
        _path_expression(
            operand
        )
        for operand in operands
    ):
        return values

    for operand in operands:
        literal = _api_literal(
            operand
        )

        if literal is not None:
            values.add(
                literal
            )

        if isinstance(
            operand,
            (
                ast.Set,
                ast.Tuple,
                ast.List,
            ),
        ):
            for element in operand.elts:
                literal = _api_literal(
                    element
                )

                if literal is not None:
                    values.add(
                        literal
                    )

    return values


def _startswith_prefixes(
    node: ast.AST,
) -> set[str]:
    values: set[str] = set()

    for candidate in ast.walk(
        node
    ):
        if not isinstance(
            candidate,
            ast.Call,
        ):
            continue

        function = candidate.func

        if not isinstance(
            function,
            ast.Attribute,
        ):
            continue

        if function.attr != "startswith":
            continue

        if not _path_expression(
            function.value
        ):
            continue

        if not candidate.args:
            continue

        literal = _api_literal(
            candidate.args[0]
        )

        if literal is None:
            continue

        values.add(
            literal
        )

    return values


def _parameterized_api_literals(
    node: ast.AST,
) -> set[str]:
    values: set[str] = set()

    for candidate in ast.walk(
        node
    ):
        literal = _api_literal(
            candidate
        )

        if literal is None:
            continue

        if (
            "{"
            not in literal
            or "}"
            not in literal
        ):
            continue

        values.add(
            literal
        )

    return values


def _prefix_matches_template(
    prefix: str,
    template: str,
) -> bool:
    if (
        "{"
        not in template
        or "}"
        not in template
    ):
        return False

    static_prefix = template.split(
        "{",
        1,
    )[0]

    return (
        prefix == static_prefix
        or prefix.rstrip("/")
        == static_prefix.rstrip("/")
    )


def _method_api_paths(
    node: ast.AST,
) -> set[str]:
    exact: set[str] = set()

    for candidate in ast.walk(
        node
    ):
        if isinstance(
            candidate,
            ast.Compare,
        ):
            exact.update(
                _comparison_routes(
                    candidate
                )
            )

    prefixes = _startswith_prefixes(
        node
    )

    templates = _parameterized_api_literals(
        node
    )

    result = set(
        exact
    )

    for template in templates:
        if any(
            _prefix_matches_template(
                prefix,
                template,
            )
            for prefix in prefixes
        ):
            result.add(
                template
            )

    # A raw startswith prefix is evidence of a family of routes,
    # not itself necessarily a callable endpoint. Do not emit it.
    return result


def discover_api_endpoints(
    workspace: Path,
) -> tuple[ApiEndpoint, ...]:
    root = workspace.resolve()

    values: set[
        tuple[str, str, str]
    ] = set()

    method_names = {
        "do_GET": "GET",
        "do_POST": "POST",
        "do_PUT": "PUT",
        "do_PATCH": "PATCH",
        "do_DELETE": "DELETE",
    }

    for path in python_sources(
        root
    ):
        source = path.read_text(
            encoding="utf-8",
            errors="ignore",
        )

        try:
            tree = ast.parse(
                source
            )
        except SyntaxError:
            continue

        relative = path.relative_to(
            root
        ).as_posix()

        for node in ast.walk(
            tree
        ):
            if not isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            ):
                continue

            method = method_names.get(
                node.name
            )

            if method is None:
                continue

            for route in _method_api_paths(
                node
            ):
                values.add(
                    (
                        method,
                        route,
                        relative,
                    )
                )

    return tuple(
        ApiEndpoint(
            method=method,
            path=route,
            source=source,
        )
        for method, route, source in sorted(
            values
        )
    )


def discover_api_paths(
    workspace: Path,
) -> tuple[str, ...]:
    values: set[str] = set()

    pattern = re.compile(
        r'''["'](
            /api/
            [A-Za-z0-9_./{}-]+
        )["']''',
        re.X,
    )

    for path in python_sources(
        workspace
    ):
        source = path.read_text(
            encoding="utf-8",
            errors="ignore",
        )

        for match in pattern.finditer(
            source
        ):
            value = match.group(1)

            # Parameterized paths cannot be mechanically GET-probed
            # without first obtaining an identifier.
            if (
                "{"
                in value
                or "}"
                in value
            ):
                continue

            values.add(value)

    return tuple(
        sorted(
            values
        )
    )


def _accepts_port_environment(
    entrypoint: Path,
) -> bool:
    source = entrypoint.read_text(
        encoding="utf-8",
        errors="ignore",
    )

    return bool(
        re.search(
            r'''(?:os\.environ|os\.getenv).*?PORT''',
            source,
            flags=(
                re.I
                | re.S
            ),
        )
    )


def discover_runtime(
    workspace: Path,
) -> FullStackRuntime:
    root = workspace.resolve()

    entrypoint = discover_entrypoint(
        root
    )

    if entrypoint is None:
        raise ValueError(
            "No generated Python HTTP server "
            "entrypoint was discovered."
        )

    relative = entrypoint.relative_to(
        root
    ).as_posix()

    host = "127.0.0.1"

    declared_port = discover_declared_port(
        entrypoint
    )

    environment: dict[str, str] = {}

    if _accepts_port_environment(
        entrypoint
    ):
        port = choose_free_port(
            host
        )

        environment[
            "PORT"
        ] = str(
            port
        )

    elif declared_port is not None:
        port = declared_port

    else:
        raise ValueError(
            "Generated server does not expose a "
            "provable runtime port. It must either "
            "read PORT from the environment or use "
            "a literal loopback port."
        )

    return FullStackRuntime(
        entrypoint=relative,
        host=host,
        port=port,
        command=(
            sys.executable,
            relative,
        ),
        environment=environment,
        health_path="/",
        api_paths=discover_api_paths(
            root
        ),
        api_endpoints=discover_api_endpoints(
            root
        ),
    )


def service_manifest_for_runtime(
    runtime: FullStackRuntime,
    *,
    name: str = "generated-app",
) -> ServiceManifest:
    return ServiceManifest(
        name=name,
        services=(
            ServiceSpec(
                name="web",
                command=runtime.command,
                workdir=".",
                environment=dict(
                    runtime.environment
                ),
                restart="no",
                # Startup readiness only proves that the generated
                # service has bound its runtime port. Real HTTP routes,
                # response bodies, status codes, and grounded mutations
                # are verified separately by full-stack verification.
                #
                # Using TCP here avoids treating temporary response
                # scheduling latency on loaded CI hosts as application
                # startup failure.
                health=HealthCheck(
                    kind="tcp",
                    host=runtime.host,
                    port=runtime.port,
                    timeout_seconds=3.0,
                ),
            ),
        ),
    )


def discover_service_manifest(
    workspace: Path,
    *,
    name: str = "generated-app",
) -> tuple[
    FullStackRuntime,
    ServiceManifest,
]:
    runtime = discover_runtime(
        workspace
    )

    manifest = service_manifest_for_runtime(
        runtime,
        name=name,
    )

    return (
        runtime,
        manifest,
    )


__all__ = [
    "ApiEndpoint",
    "FullStackRuntime",
    "choose_free_port",
    "discover_api_endpoints",
    "discover_api_paths",
    "discover_declared_port",
    "discover_entrypoint",
    "discover_runtime",
    "discover_service_manifest",
    "python_sources",
    "service_manifest_for_runtime",
]
