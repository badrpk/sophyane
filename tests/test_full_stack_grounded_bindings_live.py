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
NEXT_ID = 41


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
            str(len(body)),
        )

        self.end_headers()
        self.wfile.write(
            body
        )

    def read_json(self):
        length = int(
            self.headers.get(
                "Content-Length",
                "0",
            )
        )

        if not length:
            return {}

        return json.loads(
            self.rfile.read(
                length
            ).decode(
                "utf-8"
            )
        )

    def do_GET(self):
        if self.path == "/":
            body = b"<html>BINDING_OK</html>"

            self.send_response(
                200
            )

            self.send_header(
                "Content-Type",
                "text/html",
            )

            self.send_header(
                "Content-Length",
                str(len(body)),
            )

            self.end_headers()
            self.wfile.write(
                body
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

    def do_POST(self):
        global NEXT_ID

        if self.path != "/api/tasks":
            self.send_json(
                404,
                {},
            )
            return

        payload = self.read_json()

        item_id = NEXT_ID
        NEXT_ID += 1

        item = {
            "id": item_id,
            "title": payload.get(
                "title"
            ),
            "done": False,
        }

        ITEMS[
            item_id
        ] = item

        self.send_json(
            201,
            item,
        )

    def do_PUT(self):
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

        ITEMS[
            item_id
        ].update(
            self.read_json()
        )

        self.send_json(
            200,
            ITEMS[
                item_id
            ],
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
def test_dynamic_crud(client):
    created = client.request(
        "POST",
        "/api/tasks",
        {"title": "dynamic"},
    )
    assert created == 201

    task_id = created["id"]

    updated = client.request(
        "PUT",
        f"/api/tasks/{task_id}",
        {"done": True},
    )
    assert updated == 200

    deleted = client.request(
        "DELETE",
        f"/api/tasks/{task_id}",
    )
    assert deleted == 204
'''.strip()
        + "\n",
        encoding="utf-8",
    )


def test_response_bound_crud_executes_real_returned_identifier(
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
        "scenario_bind="
        "task_id<-response.id"
        in evidence
    )

    # Server starts at 41. This proves the later routes use the actual response
    # value rather than a guessed or hard-coded identifier.
    assert (
        "scenario_api=PUT /api/tasks/41 "
        "status=200"
        in evidence
    )

    assert (
        "scenario_api=DELETE /api/tasks/41 "
        "status=204"
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


def test_missing_response_binding_field_fails_closed(
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
        body = b"ok"

        if self.path == "/api/tasks":
            body = b"[]"

        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = json.dumps(
            {
                "title": "no id"
            }
        ).encode()

        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_DELETE(self):
        self.send_response(204)
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
def test_delete(client):
    created = client.request(
        "POST",
        "/api/tasks",
        {"title": "x"},
    )

    task_id = created["id"]

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

    assert not ok

    assert (
        "field 'id' absent"
        in evidence
    )
