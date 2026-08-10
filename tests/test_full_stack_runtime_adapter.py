from __future__ import annotations

from pathlib import Path

import pytest

from sophyane.full_stack_runtime import (
    discover_api_paths,
    discover_entrypoint,
    discover_runtime,
    discover_service_manifest,
)


def test_discovers_backend_app(
    tmp_path: Path,
) -> None:
    backend = tmp_path / "backend"
    backend.mkdir()

    target = backend / "app.py"

    target.write_text(
        """
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8123

class Handler(BaseHTTPRequestHandler):
    pass

if __name__ == "__main__":
    ThreadingHTTPServer(
        ("127.0.0.1", PORT),
        Handler,
    ).serve_forever()
""".strip()
        + "\n",
        encoding="utf-8",
    )

    assert (
        discover_entrypoint(
            tmp_path
        )
        == target
    )

    runtime = discover_runtime(
        tmp_path
    )

    assert runtime.entrypoint == (
        "backend/app.py"
    )

    assert runtime.port == 8123

    assert runtime.command[-1] == (
        "backend/app.py"
    )


def test_environment_port_gets_ephemeral_runtime_port(
    tmp_path: Path,
) -> None:
    target = tmp_path / "app.py"

    target.write_text(
        """
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "8080"))

if __name__ == "__main__":
    ThreadingHTTPServer(
        ("127.0.0.1", PORT),
        BaseHTTPRequestHandler,
    ).serve_forever()
""".strip()
        + "\n",
        encoding="utf-8",
    )

    runtime = discover_runtime(
        tmp_path
    )

    assert 1 <= runtime.port <= 65535

    assert runtime.environment == {
        "PORT": str(runtime.port),
    }


def test_discovers_static_api_paths(
    tmp_path: Path,
) -> None:
    target = tmp_path / "server.py"

    target.write_text(
        """
from http.server import BaseHTTPRequestHandler

PATHS = (
    "/api/projects",
    "/api/tasks",
    "/api/stats",
    "/api/tasks/{id}",
)
""".strip()
        + "\n",
        encoding="utf-8",
    )

    assert discover_api_paths(
        tmp_path
    ) == (
        "/api/projects",
        "/api/stats",
        "/api/tasks",
    )


def test_manifest_reuses_service_fabric_model(
    tmp_path: Path,
) -> None:
    target = tmp_path / "server.py"

    target.write_text(
        """
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 9090

if __name__ == "__main__":
    HTTPServer(
        ("127.0.0.1", PORT),
        BaseHTTPRequestHandler,
    ).serve_forever()
""".strip()
        + "\n",
        encoding="utf-8",
    )

    runtime, manifest = (
        discover_service_manifest(
            tmp_path
        )
    )

    assert manifest.name == (
        "generated-app"
    )

    assert len(
        manifest.services
    ) == 1

    service = manifest.services[0]

    assert service.command == (
        runtime.command
    )

    assert service.health.kind == "http"

    assert service.health.port == 9090

    assert service.restart == "no"


def test_unknown_runtime_port_fails_closed(
    tmp_path: Path,
) -> None:
    target = tmp_path / "main.py"

    target.write_text(
        """
from http.server import BaseHTTPRequestHandler, HTTPServer

def start(value):
    HTTPServer(
        ("127.0.0.1", value),
        BaseHTTPRequestHandler,
    ).serve_forever()

if __name__ == "__main__":
    start(compute_port())
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="provable runtime port",
    ):
        discover_runtime(
            tmp_path
        )


def test_no_server_fails_closed(
    tmp_path: Path,
) -> None:
    (tmp_path / "worker.py").write_text(
        "print('worker')\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="entrypoint",
    ):
        discover_runtime(
            tmp_path
        )
