from __future__ import annotations

import http.client
import json
import time
from pathlib import Path

from sophyane.full_stack_runtime import (
    discover_service_manifest,
)
from sophyane.service_fabric.supervisor import (
    ServiceSupervisor,
)


def _write_application(
    root: Path,
) -> None:
    backend = root / "backend"
    backend.mkdir(
        parents=True,
        exist_ok=True,
    )

    static = root / "static"
    static.mkdir(
        parents=True,
        exist_ok=True,
    )

    (static / "index.html").write_text(
        """
<!doctype html>
<html>
<head>
<meta name="viewport"
      content="width=device-width,initial-scale=1">
<title>Sophyane Integration</title>
</head>
<body>
<h1>Project Dashboard</h1>
</body>
</html>
""".strip()
        + "\n",
        encoding="utf-8",
    )

    (backend / "app.py").write_text(
        r'''
from __future__ import annotations

import json
import os
from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)
from pathlib import Path


PORT = int(
    os.environ.get(
        "PORT",
        "8080",
    )
)

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "static" / "index.html"


class Handler(BaseHTTPRequestHandler):
    def _json(
        self,
        payload,
        status=200,
    ):
        body = json.dumps(
            payload
        ).encode(
            "utf-8"
        )

        self.send_response(
            status
        )
        self.send_header(
            "Content-Type",
            "application/json",
        )
        self.send_header(
            "Content-Length",
            str(len(body)),
        )
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split(
            "?",
            1,
        )[0]

        if path == "/":
            body = INDEX.read_bytes()

            self.send_response(200)
            self.send_header(
                "Content-Type",
                "text/html; charset=utf-8",
            )
            self.send_header(
                "Content-Length",
                str(len(body)),
            )
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/projects":
            self._json(
                [
                    {
                        "id": 1,
                        "name": "Demo Project",
                    }
                ]
            )
            return

        if path == "/api/tasks":
            self._json(
                [
                    {
                        "id": 1,
                        "title": "Verify Sophyane",
                        "status": "todo",
                    }
                ]
            )
            return

        if path == "/api/stats":
            self._json(
                {
                    "projects": 1,
                    "tasks": 1,
                }
            )
            return

        self._json(
            {
                "error": "not found",
            },
            404,
        )

    def log_message(
        self,
        _format,
        *_args,
    ):
        return


if __name__ == "__main__":
    ThreadingHTTPServer(
        (
            "127.0.0.1",
            PORT,
        ),
        Handler,
    ).serve_forever()
'''.strip()
        + "\n",
        encoding="utf-8",
    )


def _request(
    host: str,
    port: int,
    path: str,
) -> tuple[
    int,
    str,
    bytes,
]:
    connection = http.client.HTTPConnection(
        host,
        port,
        timeout=3,
    )

    try:
        connection.request(
            "GET",
            path,
        )

        response = connection.getresponse()

        return (
            int(response.status),
            str(
                response.getheader(
                    "Content-Type",
                    "",
                )
            ),
            response.read(),
        )

    finally:
        connection.close()


def _wait_healthy(
    supervisor: ServiceSupervisor,
    *,
    timeout: float = 5.0,
) -> dict[str, object]:
    deadline = (
        time.monotonic()
        + timeout
    )

    last: list[
        dict[str, object]
    ] = []

    while time.monotonic() < deadline:
        last = supervisor.status()

        if (
            len(last) == 1
            and last[0]["alive"] is True
            and last[0]["healthy"] is True
        ):
            return last[0]

        time.sleep(
            0.1
        )

    raise AssertionError(
        "Service never became healthy: "
        + repr(last)
    )


def test_generated_application_runs_through_service_fabric(
    tmp_path: Path,
) -> None:
    _write_application(
        tmp_path
    )

    runtime, manifest = (
        discover_service_manifest(
            tmp_path,
            name="integration-app",
        )
    )

    events: list[str] = []

    supervisor = ServiceSupervisor(
        workspace=tmp_path,
        progress=events.append,
    )

    try:
        running = supervisor.start_manifest(
            manifest
        )

        assert len(running) == 1

        assert (
            running[0].spec.name
            == "web"
        )

        status = _wait_healthy(
            supervisor
        )

        assert status["alive"] is True
        assert status["healthy"] is True

        assert (
            str(status["health"])
            == "http-status=200"
        )

        assert int(
            status["pid"]
        ) > 0

        log = Path(
            str(status["log"])
        )

        assert log.is_file()

        code, content_type, body = _request(
            runtime.host,
            runtime.port,
            "/",
        )

        assert code == 200

        assert (
            "text/html"
            in content_type
        )

        assert (
            b"Project Dashboard"
            in body
        )

        expected_api = {
            "/api/projects",
            "/api/tasks",
            "/api/stats",
        }

        assert expected_api.issubset(
            set(runtime.api_paths)
        )

        for path in sorted(
            expected_api
        ):
            code, content_type, body = (
                _request(
                    runtime.host,
                    runtime.port,
                    path,
                )
            )

            assert code == 200

            assert (
                "application/json"
                in content_type
            )

            payload = json.loads(
                body.decode(
                    "utf-8"
                )
            )

            assert payload is not None

        assert any(
            "Service Fabric: starting web"
            in event
            for event in events
        )

    finally:
        supervisor.stop_all()

    assert supervisor.status() == []

    assert any(
        "Service Fabric: stopping web"
        in event
        for event in events
    )


def test_environment_port_and_service_health_agree(
    tmp_path: Path,
) -> None:
    _write_application(
        tmp_path
    )

    runtime, manifest = (
        discover_service_manifest(
            tmp_path
        )
    )

    service = manifest.services[0]

    assert (
        runtime.environment["PORT"]
        == str(runtime.port)
    )

    assert (
        service.environment["PORT"]
        == str(runtime.port)
    )

    assert (
        service.health.port
        == runtime.port
    )

    assert (
        service.health.host
        == runtime.host
    )


def test_supervisor_stop_releases_generated_server(
    tmp_path: Path,
) -> None:
    _write_application(
        tmp_path
    )

    runtime, manifest = (
        discover_service_manifest(
            tmp_path
        )
    )

    supervisor = ServiceSupervisor(
        workspace=tmp_path,
    )

    supervisor.start_manifest(
        manifest
    )

    _wait_healthy(
        supervisor
    )

    assert (
        _request(
            runtime.host,
            runtime.port,
            "/",
        )[0]
        == 200
    )

    supervisor.stop_all()

    assert supervisor.status() == []

    connection = http.client.HTTPConnection(
        runtime.host,
        runtime.port,
        timeout=0.5,
    )

    try:
        try:
            connection.request(
                "GET",
                "/",
            )

            connection.getresponse()

        except OSError:
            pass

        else:
            raise AssertionError(
                "Generated service remained reachable "
                "after Service Fabric stop_all()."
            )

    finally:
        connection.close()
