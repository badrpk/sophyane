from pathlib import Path

from sophyane.execution_runtime import (
    _normalize_action,
    extract_plan,
)
from sophyane.full_stack_verification import (
    detect_backend_semantic_defects,
)


def test_rejects_threaded_global_sqlite_connection() -> None:
    source = """
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

conn = sqlite3.connect("app.db", check_same_thread=False)
cursor = conn.cursor()

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/items":
            cursor.execute("SELECT * FROM items")
"""

    defects = detect_backend_semantic_defects(
        source
    )

    assert (
        "threaded_server_uses_shared_sqlite_connection"
        in defects
    )


def test_rejects_html_errors_for_json_api() -> None:
    source = """
from http.server import BaseHTTPRequestHandler

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/api/items":
            self.send_error(400, "bad request")
"""

    defects = detect_backend_semantic_defects(
        source
    )

    assert (
        "api_errors_are_not_structured_json"
        in defects
    )


def test_accepts_per_request_sqlite_and_json_error_helper() -> None:
    source = """
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

def get_db():
    return sqlite3.connect("app.db")

def init_db():
    with get_db() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS items "
            "(id INTEGER PRIMARY KEY, name TEXT NOT NULL)"
        )

class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/api/items":
            self._send_json(404, {"error": "not found"})
            return

        try:
            data = json.loads(
                self.rfile.read(
                    int(self.headers.get("Content-Length", "0"))
                )
            )
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON"})
            return
"""

    defects = detect_backend_semantic_defects(
        source
    )

    assert (
        "threaded_server_uses_shared_sqlite_connection"
        not in defects
    )

    assert (
        "api_errors_are_not_structured_json"
        not in defects
    )

    assert (
        "malformed_json_request_not_handled"
        not in defects
    )


def test_exact_live_qwen_backend_is_semantically_rejected() -> None:
    path = (
        Path.home()
        / ".local"
        / "state"
        / "sophyane"
        / "local-gguf-real-coding-output-20260811-010654.txt"
    )

    if not path.is_file():
        return

    raw = path.read_text(
        encoding="utf-8"
    )

    plan = extract_plan(
        raw
    )

    assert plan is not None

    action = _normalize_action(
        plan
    )

    assert action is not None

    defects = detect_backend_semantic_defects(
        action["content"]
    )

    print(
        "DEFECTS:",
        defects,
    )

    assert (
        "threaded_server_uses_shared_sqlite_connection"
        in defects
    )

    assert (
        "api_errors_are_not_structured_json"
        in defects
    )
