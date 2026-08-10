from __future__ import annotations

from pathlib import Path

from sophyane.full_stack_verification import (
    verify_full_stack_application,
)


def _write_project(
    root: Path,
) -> None:
    backend = root / "backend"
    tests = root / "tests"

    backend.mkdir()
    tests.mkdir()

    (backend / "app.py").write_text(
        r'''
from __future__ import annotations

import json
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

ITEMS = {}


class Handler(BaseHTTPRequestHandler):
    def send_json(
        self,
        status,
        payload,
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
            str(
                len(
                    body
                )
            ),
        )

        self.end_headers()

        self.wfile.write(
            body
        )

    def read_json(
        self,
    ):
        length = int(
            self.headers.get(
                "Content-Length",
                "0",
            )
        )

        if not length:
            return {}

        try:
            return json.loads(
                self.rfile.read(
                    length
                ).decode(
                    "utf-8"
                )
            )
        except json.JSONDecodeError:
            self.send_json(
                400,
                {
                    "error":
                        "invalid JSON",
                },
            )
            return None

    def do_GET(self):
        path = self.path.split(
            "?",
            1,
        )[0]

        if path == "/":
            body = (
                b"<html><body>"
                b"GROUNDED_CRUD_OK"
                b"</body></html>"
            )

            self.send_response(
                200
            )

            self.send_header(
                "Content-Type",
                "text/html",
            )

            self.send_header(
                "Content-Length",
                str(
                    len(
                        body
                    )
                ),
            )

            self.end_headers()

            self.wfile.write(
                body
            )

            return

        if path == "/api/tasks":
            self.send_json(
                200,
                list(
                    ITEMS.values()
                ),
            )
            return

        self.send_json(
            404,
            {
                "error": "not found",
            },
        )

    def do_POST(self):
        if self.path == "/api/tasks":
            payload = self.read_json()

            if payload is None:
                return

            item = {
                "id": 7,
                "title": payload.get(
                    "title"
                ),
                "done": False,
            }

            ITEMS[
                7
            ] = item

            self.send_json(
                201,
                item,
            )

            return

        self.send_json(
            404,
            {},
        )

    def do_PUT(self):
        if self.path == "/api/tasks/7":
            payload = self.read_json()

            if payload is None:
                return

            if 7 not in ITEMS:
                self.send_json(
                    404,
                    {},
                )
                return

            ITEMS[
                7
            ].update(
                payload
            )

            self.send_json(
                200,
                ITEMS[
                    7
                ],
            )

            return

        self.send_json(
            404,
            {},
        )

    def do_DELETE(self):
        if self.path == "/api/tasks/7":
            ITEMS.pop(
                7,
                None,
            )

            self.send_response(
                204
            )

            self.end_headers()

            return

        self.send_json(
            404,
            {},
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

    (tests / "test_api_contract.py").write_text(
        '''
def test_grounded_crud(client):
    created = client.request(
        "POST",
        "/api/tasks",
        {"title": "Grounded task"},
    )
    assert created == 201

    updated = client.request(
        "PUT",
        "/api/tasks/7",
        {"done": True},
    )
    assert updated == 200

    deleted = client.request(
        "DELETE",
        "/api/tasks/7",
    )
    assert deleted == 204
'''.strip()
        + "\n",
        encoding="utf-8",
    )


def test_grounded_mutation_sequence_runs_through_service_fabric(
    tmp_path: Path,
) -> None:
    _write_project(
        tmp_path
    )

    events: list[str] = []

    ok, evidence = (
        verify_full_stack_application(
            tmp_path,
            events.append,
        )
    )

    assert ok, evidence

    assert (
        "scenario_api=POST /api/tasks "
        "status=201"
        in evidence
    )

    assert (
        "scenario_api=PUT /api/tasks/7 "
        "status=200"
        in evidence
    )

    assert (
        "scenario_api=DELETE /api/tasks/7 "
        "status=204"
        in evidence
    )

    assert (
        "scenario=test_grounded_crud"
        in evidence
    )

    assert any(
        "Service Fabric: starting"
        in event
        for event in events
    )

    assert any(
        "Service Fabric: stopping"
        in event
        for event in events
    )


def test_no_grounded_scenario_means_no_mutation_request(
    tmp_path: Path,
) -> None:
    backend = (
        tmp_path
        / "backend"
    )

    backend.mkdir()

    marker = (
        tmp_path
        / "mutation-called"
    )

    (backend / "app.py").write_text(
        r'''
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

ROOT = Path(
    __file__
).resolve().parent.parent

MARKER = (
    ROOT
    / "mutation-called"
)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            body = b"ok"

            self.send_response(
                200
            )

            self.send_header(
                "Content-Length",
                str(
                    len(
                        body
                    )
                ),
            )

            self.end_headers()
            self.wfile.write(
                body
            )
            return

        if self.path == "/api/items":
            body = b"[]"

            self.send_response(
                200
            )

            self.send_header(
                "Content-Type",
                "application/json",
            )

            self.send_header(
                "Content-Length",
                str(
                    len(
                        body
                    )
                ),
            )

            self.end_headers()
            self.wfile.write(
                body
            )
            return

        self.send_response(
            404
        )
        self.end_headers()

    def do_POST(self):
        if self.path == "/api/items":
            MARKER.write_text(
                "called\\n",
                encoding="utf-8",
            )

            self.send_response(
                201
            )
            self.end_headers()
            return

        self.send_response(
            404
        )
        self.end_headers()

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

    ok, evidence = (
        verify_full_stack_application(
            tmp_path,
        )
    )

    assert ok, evidence

    assert not marker.exists()

    assert (
        "mutation_contracts_unexecuted="
        in evidence
    )
