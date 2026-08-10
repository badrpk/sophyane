from __future__ import annotations

from pathlib import Path

from sophyane.full_stack_verification import (
    verify_full_stack_application,
)


def _write_multi_binding_project(
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "8080"))

TASK_ID = 51
OWNER_ID = 702


class Handler(BaseHTTPRequestHandler):
    def _json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read(self):
        length = int(self.headers.get("Content-Length", "0"))

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
            self._json(
                400,
                {
                    "error":
                        "invalid JSON",
                },
            )
            return None

    def do_GET(self):
        if self.path == "/":
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/api/tasks":
            self._json(200, [])
            return

        self._json(404, {})

    def do_POST(self):
        if self.path == "/api/tasks":
            payload = self._read()

            if payload is None:
                return

            self._json(
                201,
                {
                    "id": TASK_ID,
                    "owner_id": OWNER_ID,
                },
            )
            return

        self._json(404, {})

    def do_PUT(self):
        expected = (
            f"/api/tasks/{TASK_ID}/owners/{OWNER_ID}"
        )

        if self.path == expected:
            payload = self._read()

            if payload is None:
                return

            self._json(
                200,
                {
                    "ok": True,
                },
            )
            return

        self._json(
            409,
            {
                "received": self.path,
                "expected": expected,
            },
        )

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
def test_multi_binding(client):
    created = client.request(
        "POST",
        "/api/tasks",
        {"title": "dynamic"},
    )
    assert created == 201

    task_id = created["id"]
    owner_id = created["owner_id"]

    updated = client.request(
        "PUT",
        f"/api/tasks/{task_id}/owners/{owner_id}",
        {"done": True},
    )
    assert updated == 200
'''.strip()
        + "\n",
        encoding="utf-8",
    )


def test_live_request_uses_both_actual_response_values(
    tmp_path: Path,
) -> None:
    _write_multi_binding_project(
        tmp_path
    )

    ok, evidence = (
        verify_full_stack_application(
            tmp_path
        )
    )

    assert ok, evidence

    assert (
        "scenario_bind=task_id<-response.id"
        in evidence
    )

    assert (
        "scenario_bind=owner_id<-response.owner_id"
        in evidence
    )

    assert (
        "scenario_api=PUT "
        "/api/tasks/51/owners/702 "
        "status=200"
        in evidence
    )


def test_shadowed_symbol_does_not_drive_dynamic_request(
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
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/api/tasks":
            self.send_response(404)
            self.end_headers()
            return

        body = json.dumps({"id": 12}).encode()
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_DELETE(self):
        if self.path.startswith("/api/tasks/"):
            # Ground the parameterized server route contract while preserving
            # the proof that this request must never be driven after shadowing.
            route = "/api/tasks/{id}"
            self.send_response(500)
            self.end_headers()
            return

        self.send_response(404)
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
def test_shadow(client):
    created = client.request(
        "POST",
        "/api/tasks",
        {"title": "x"},
    )

    task_id = created["id"]

    task_id = external_value

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
        "scenario_api=DELETE"
        not in evidence
    )


def test_multi_binding_is_atomic_when_one_field_is_missing(
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
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/api/tasks":
            self.send_response(404)
            self.end_headers()
            return

        body = json.dumps({"id": 33}).encode()
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_PUT(self):
        if self.path.startswith("/api/tasks/"):
            route = "/api/tasks/{task_id}/owners/{owner_id}"
            self.send_response(200)
            self.end_headers()
            return

        self.send_response(404)
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
def test_atomic(client):
    created = client.request(
        "POST",
        "/api/tasks",
        {"title": "x"},
    )

    task_id = created["id"]
    owner_id = created["owner_id"]

    client.request(
        "PUT",
        f"/api/tasks/{task_id}/owners/{owner_id}",
        {},
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
        "field 'owner_id' absent"
        in evidence
    )

    assert (
        "scenario_api=PUT"
        not in evidence
    )
