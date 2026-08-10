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

ITEMS = {
    73: {
        "id": 73,
        "title": "selected",
    }
}


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
                len(body)
            ),
        )

        self.end_headers()
        self.wfile.write(
            body
        )

    def do_GET(self):
        if self.path == "/":
            body = b"<html>GET_BIND_OK</html>"

            self.send_response(
                200
            )

            self.send_header(
                "Content-Length",
                str(
                    len(body)
                ),
            )

            self.end_headers()
            self.wfile.write(
                body
            )
            return

        if self.path == "/api/selected":
            self.send_json(
                200,
                {
                    "id": 73,
                },
            )
            return

        if self.path == "/api/tasks":
            self.send_json(
                200,
                list(
                    ITEMS.values()
                ),
            )
            return

        self.send_json(
            404,
            {},
        )

    def do_DELETE(self):
        if not self.path.startswith(
            "/api/tasks/"
        ):
            self.send_json(
                404,
                {},
            )
            return

        item_id = int(
            self.path.rsplit(
                "/",
                1,
            )[-1]
        )

        if item_id not in ITEMS:
            self.send_json(
                404,
                {},
            )
            return

        ITEMS.pop(
            item_id
        )

        self.send_response(
            204
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

    (tests / "test_api_contract.py").write_text(
        '''
def test_delete_selected(client):
    selected = client.request(
        "GET",
        "/api/selected",
    )
    assert selected == 200

    task_id = selected["id"]

    deleted = client.request(
        "DELETE",
        f"/api/tasks/{task_id}",
    )
    assert deleted == 204
'''.strip()
        + "\n",
        encoding="utf-8",
    )


def test_get_response_binding_executes_actual_identifier(
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
        "scenario_api=GET /api/selected "
        "status=200"
        in evidence
    )

    assert (
        "scenario_bind="
        "task_id<-response.id"
        in evidence
    )

    assert (
        "scenario_api=DELETE /api/tasks/73 "
        "status=204"
        in evidence
    )

    assert any(
        "Service Fabric: stopping"
        in event
        for event in events
    )


def test_wrong_response_must_not_supply_binding(
    tmp_path: Path,
) -> None:
    backend = tmp_path / "backend"
    tests = tmp_path / "tests"

    backend.mkdir()
    tests.mkdir()

    (backend / "app.py").write_text(
        r'''
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "8080"))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            body = b"ok"
            kind = "text/plain"

        elif self.path == "/api/first":
            body = json.dumps(
                {
                    "id": 91
                }
            ).encode()
            kind = "application/json"

        elif self.path == "/api/second":
            body = json.dumps(
                {
                    "id": 92
                }
            ).encode()
            kind = "application/json"

        else:
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_DELETE(self):
        if self.path == "/api/tasks/91":
            self.send_response(204)
        else:
            self.send_response(409)

        self.end_headers()

    def log_message(self, *_args):
        return


ThreadingHTTPServer(
    ("127.0.0.1", PORT),
    Handler,
).serve_forever()
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    (tests / "test_contract.py").write_text(
        '''
def test_provenance(client):
    first = client.request(
        "GET",
        "/api/first",
    )

    second = client.request(
        "GET",
        "/api/second",
    )

    task_id = first["id"]

    client.request(
        "DELETE",
        f"/api/tasks/{task_id}",
    )
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    ok, evidence = (
        verify_full_stack_application(
            tmp_path
        )
    )

    assert ok, evidence

    assert (
        "scenario_api=DELETE /api/tasks/91 "
        in evidence
    )

    assert (
        "scenario_api=DELETE /api/tasks/92 "
        not in evidence
    )
