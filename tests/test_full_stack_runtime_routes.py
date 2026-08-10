from __future__ import annotations

from pathlib import Path

from sophyane.full_stack_runtime import (
    discover_api_endpoints,
    discover_runtime,
)


def _write_server(
    root: Path,
) -> None:
    target = root / "app.py"

    target.write_text(
        r'''
import os
from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)

PORT = int(
    os.environ.get(
        "PORT",
        "8080",
    )
)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/projects":
            return

        if self.path == "/api/tasks":
            return

    def do_POST(self):
        if self.path == "/api/tasks":
            return

    def do_PUT(self):
        if self.path.startswith("/api/tasks/"):
            # Documentation/contract literal for the route shape:
            route = "/api/tasks/{id}"
            return

    def do_DELETE(self):
        route = "/api/tasks/{id}"

        if self.path.startswith("/api/tasks/"):
            return


ThreadingHTTPServer(
    ("127.0.0.1", PORT),
    Handler,
).serve_forever()
'''.strip()
        + "\n",
        encoding="utf-8",
    )


def test_discovers_http_methods_and_paths(
    tmp_path: Path,
) -> None:
    _write_server(
        tmp_path
    )

    endpoints = discover_api_endpoints(
        tmp_path
    )

    pairs = {
        (
            item.method,
            item.path,
        )
        for item in endpoints
    }

    assert (
        "GET",
        "/api/projects",
    ) in pairs

    assert (
        "GET",
        "/api/tasks",
    ) in pairs

    assert (
        "POST",
        "/api/tasks",
    ) in pairs

    assert (
        "PUT",
        "/api/tasks/{id}",
    ) in pairs

    assert (
        "DELETE",
        "/api/tasks/{id}",
    ) in pairs


def test_runtime_exposes_endpoint_contract(
    tmp_path: Path,
) -> None:
    _write_server(
        tmp_path
    )

    runtime = discover_runtime(
        tmp_path
    )

    assert runtime.api_endpoints

    assert any(
        endpoint.method == "POST"
        and endpoint.path == "/api/tasks"
        for endpoint in runtime.api_endpoints
    )


def test_method_scope_prevents_false_get_classification(
    tmp_path: Path,
) -> None:
    target = tmp_path / "app.py"

    target.write_text(
        r'''
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get("PORT", "8080"))


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/api/create":
            return


HTTPServer(
    ("127.0.0.1", PORT),
    Handler,
).serve_forever()
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    endpoints = discover_api_endpoints(
        tmp_path
    )

    pairs = {
        (
            endpoint.method,
            endpoint.path,
        )
        for endpoint in endpoints
    }

    assert (
        "POST",
        "/api/create",
    ) in pairs

    assert (
        "GET",
        "/api/create",
    ) not in pairs


def test_unrelated_api_literal_outside_handler_is_not_endpoint(
    tmp_path: Path,
) -> None:
    target = tmp_path / "app.py"

    target.write_text(
        r'''
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get("PORT", "8080"))

DOCUMENTATION = "/api/not-a-handler"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/live":
            return


HTTPServer(
    ("127.0.0.1", PORT),
    Handler,
).serve_forever()
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    pairs = {
        (
            endpoint.method,
            endpoint.path,
        )
        for endpoint in discover_api_endpoints(
            tmp_path
        )
    }

    assert (
        "GET",
        "/api/live",
    ) in pairs

    assert all(
        path != "/api/not-a-handler"
        for _method, path in pairs
    )
