from pathlib import Path

import sophyane.full_stack_verification as verification


def _write_project(
    root: Path,
    backend_source: str,
) -> None:
    backend = (
        root
        / "backend"
    )

    frontend = (
        root
        / "frontend"
    )

    tests = (
        root
        / "tests"
    )

    backend.mkdir(
        parents=True,
        exist_ok=True,
    )

    frontend.mkdir(
        parents=True,
        exist_ok=True,
    )

    tests.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        backend
        / "app.py"
    ).write_text(
        backend_source,
        encoding="utf-8",
    )

    (
        frontend
        / "index.html"
    ).write_text(
        """<!doctype html>
<html>
<body>
<h1>Items</h1>
<script>
fetch("/api/items")
</script>
</body>
</html>
""",
        encoding="utf-8",
    )

    (
        tests
        / "test_api.py"
    ).write_text(
        "def test_placeholder(): assert True\n",
        encoding="utf-8",
    )


def test_verifier_rejects_semantically_unsafe_backend_before_start(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_project(
        tmp_path,
        """
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

conn = sqlite3.connect("app.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute(
    "CREATE TABLE IF NOT EXISTS items "
    "(id INTEGER PRIMARY KEY, name TEXT)"
)
conn.commit()

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/items":
            cursor.execute("SELECT * FROM items")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"[]")
        else:
            self.send_error(404, "not found")

def run():
    ThreadingHTTPServer(
        ("127.0.0.1", 8769),
        Handler,
    ).serve_forever()

if __name__ == "__main__":
    run()
""",
    )

    class Runtime:
        entrypoint = "backend/app.py"
        api_endpoints = (
            type(
                "Endpoint",
                (),
                {
                    "method": "GET",
                    "path": "/api/items",
                },
            )(),
        )
        base_url = "http://127.0.0.1:8769"
        host = "127.0.0.1"
        port = 8769
        health_path = "/"

    runtime = Runtime()

    monkeypatch.setattr(
        verification,
        "discover_service_manifest",
        lambda workspace, name:
            (
                runtime,
                object(),
            ),
    )

    started = False

    class Supervisor:
        def __init__(
            self,
            *,
            workspace,
            progress,
        ):
            pass

        def start_manifest(
            self,
            manifest,
        ):
            nonlocal started
            started = True
            raise AssertionError(
                "unsafe service must not start"
            )

        def stop_all(
            self,
        ):
            pass

    monkeypatch.setattr(
        verification,
        "ServiceSupervisor",
        Supervisor,
    )

    ok, evidence = (
        verification.verify_full_stack_application(
            tmp_path
        )
    )

    assert ok is False

    assert (
        "threaded_server_uses_shared_sqlite_connection"
        in evidence
    )

    assert started is False


def test_verifier_allows_semantically_safe_backend_to_reach_service_layer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_project(
        tmp_path,
        """
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

def get_db():
    return sqlite3.connect("app.db")

def init_db():
    with get_db() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS items "
            "(id INTEGER PRIMARY KEY, name TEXT)"
        )

class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/items":
            with get_db() as db:
                rows = db.execute(
                    "SELECT * FROM items"
                ).fetchall()
            self._send_json(
                200,
                {"items": rows},
            )
        else:
            self._send_json(
                404,
                {"error": "not found"},
            )

def run():
    init_db()
    ThreadingHTTPServer(
        ("127.0.0.1", 8769),
        Handler,
    ).serve_forever()

if __name__ == "__main__":
    run()
""",
    )

    class Runtime:
        entrypoint = "backend/app.py"
        api_endpoints = (
            type(
                "Endpoint",
                (),
                {
                    "method": "GET",
                    "path": "/api/items",
                },
            )(),
        )
        base_url = "http://127.0.0.1:8769"
        host = "127.0.0.1"
        port = 8769
        health_path = "/"

    runtime = Runtime()

    monkeypatch.setattr(
        verification,
        "discover_service_manifest",
        lambda workspace, name:
            (
                runtime,
                object(),
            ),
    )

    reached_service_layer = False

    class Supervisor:
        def __init__(
            self,
            *,
            workspace,
            progress,
        ):
            pass

        def start_manifest(
            self,
            manifest,
        ):
            nonlocal reached_service_layer
            reached_service_layer = True

            raise RuntimeError(
                "TEST_SERVICE_BOUNDARY"
            )

        def stop_all(
            self,
        ):
            pass

    monkeypatch.setattr(
        verification,
        "ServiceSupervisor",
        Supervisor,
    )

    ok, evidence = (
        verification.verify_full_stack_application(
            tmp_path
        )
    )

    assert reached_service_layer is True

    assert ok is False

    assert (
        "TEST_SERVICE_BOUNDARY"
        in evidence
    )
