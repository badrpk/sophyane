from __future__ import annotations

import re
from pathlib import Path

from sophyane.full_stack_verification import (
    verify_full_stack_application,
)


def _write_application(
    root: Path,
) -> None:
    backend = root / "backend"

    backend.mkdir(
        parents=True,
        exist_ok=True,
    )

    marker = root / "post-was-called"

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
POST_MARKER = ROOT / "post-was-called"


class Handler(BaseHTTPRequestHandler):
    def _send(
        self,
        status,
        payload,
        kind,
    ):
        body = payload.encode(
            "utf-8"
        )

        self.send_response(
            status
        )

        self.send_header(
            "Content-Type",
            kind,
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
            self._send(
                200,
                "<html><body>FABRIC_OK</body></html>",
                "text/html",
            )
            return

        if path == "/api/projects":
            self._send(
                200,
                json.dumps(
                    [
                        {
                            "id": 1,
                            "name": "Fabric",
                        }
                    ]
                ),
                "application/json",
            )
            return

        self._send(
            404,
            "{}",
            "application/json",
        )

    def do_POST(self):
        if self.path == "/api/tasks":
            POST_MARKER.write_text(
                "called\n",
                encoding="utf-8",
            )

            self._send(
                201,
                '{"ok":true}',
                "application/json",
            )
            return

        self._send(
            404,
            "{}",
            "application/json",
        )

    def log_message(
        self,
        *_args,
    ):
        return


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

    assert not marker.exists()


def test_service_fabric_owns_generated_runtime_verification(
    tmp_path: Path,
) -> None:
    _write_application(
        tmp_path
    )

    events: list[str] = []

    ok, result = (
        verify_full_stack_application(
            tmp_path,
            events.append,
        )
    )

    assert ok, result

    assert (
        "entrypoint=backend/app.py"
        in result
    )

    assert (
        "GET /api/projects"
        in result
    )

    assert (
        "POST /api/tasks"
        in result
    )

    assert (
        "mutation_contracts_unexecuted="
        in result
    )

    assert (
        "POST /api/tasks"
        in result
    )

    assert (
        "no grounded static request scenario"
        in result
    )

    # No fabricated POST payload should be sent merely to prove the route.
    assert not (
        tmp_path
        / "post-was-called"
    ).exists()

    assert any(
        "Service Fabric: starting web"
        in event
        for event in events
    )

    assert any(
        "Service Fabric: stopping web"
        in event
        for event in events
    )


def test_fabric_helper_reports_ephemeral_runtime_url(
    tmp_path: Path,
) -> None:
    _write_application(
        tmp_path
    )

    ok, result = (
        verify_full_stack_application(
            tmp_path,
            lambda _message:
                None,
        )
    )

    assert ok, result

    match = re.search(
        r"base_url=http://127\.0\.0\.1:(\d+)",
        result,
    )

    assert match is not None

    port = int(
        match.group(1)
    )

    assert 1 <= port <= 65535

    # Proves verification did not depend on the old fixed port.
    assert (
        "base_url=http://127.0.0.1:8080"
        not in result
    )
