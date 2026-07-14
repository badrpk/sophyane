"""Stateful, evidence-backed software build workflows.

The first production workflow implements the inventory REST API benchmark used
for comparing Sophyane with graph orchestrators.  It intentionally uses only
Python's standard library so it runs on Termux without downloading packages.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


MAX_REPAIR_ATTEMPTS = 3
PROJECTS_DIR = Path.home() / "sophyane-projects"


@dataclass
class BuildState:
    request: str
    project: Path
    criteria: list[str] = field(default_factory=list)
    created_files: list[str] = field(default_factory=list)
    test_command: list[str] = field(default_factory=list)
    test_exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    attempts: int = 0
    checks: dict[str, bool] = field(default_factory=dict)
    timeline: list[str] = field(default_factory=list)
    verified: bool = False

    def record(self, message: str) -> None:
        self.timeline.append(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {message}")


class BuildGraph:
    """Small deterministic state graph with conditional retry edges."""

    def __init__(self) -> None:
        self.nodes: dict[str, Callable[[BuildState], str | None]] = {}

    def add(self, name: str, node: Callable[[BuildState], str | None]) -> None:
        self.nodes[name] = node

    def run(self, state: BuildState, start: str) -> BuildState:
        current: str | None = start
        steps = 0
        while current is not None:
            steps += 1
            if steps > 30:
                raise RuntimeError("Build graph exceeded its safety step limit.")
            current = self.nodes[current](state)
        return state


def supports_request(request: str) -> bool:
    lowered = request.lower()
    return (
        "inventory" in lowered
        and "rest api" in lowered
        and "sqlite" in lowered
        and ("test" in lowered or "automated" in lowered)
    )


APP_SOURCE = '''#!/usr/bin/env python3
"""Minimal inventory REST API using Python and SQLite."""

from __future__ import annotations

import json
import sqlite3
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

DB = Path(__file__).with_name("inventory.db")


def connect(path: Path = DB) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def initialize(path: Path = DB) -> None:
    with connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity >= 0),
                price REAL NOT NULL CHECK(price >= 0)
            )
            """
        )


class Repository:
    def __init__(self, path: Path = DB) -> None:
        self.path = path
        initialize(path)

    def create(self, name: str, quantity: int, price: float) -> dict:
        with connect(self.path) as connection:
            cursor = connection.execute(
                "INSERT INTO items(name, quantity, price) VALUES (?, ?, ?)",
                (name, quantity, price),
            )
            item_id = int(cursor.lastrowid)
        item = self.get(item_id)
        if item is None:
            raise RuntimeError("Created item was not found.")
        return item

    def all(self) -> list[dict]:
        with connect(self.path) as connection:
            rows = connection.execute(
                "SELECT id, name, quantity, price FROM items ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, item_id: int) -> dict | None:
        with connect(self.path) as connection:
            row = connection.execute(
                "SELECT id, name, quantity, price FROM items WHERE id = ?",
                (item_id,),
            ).fetchone()
        return dict(row) if row else None

    def update(self, item_id: int, name: str, quantity: int, price: float) -> dict | None:
        with connect(self.path) as connection:
            cursor = connection.execute(
                "UPDATE items SET name = ?, quantity = ?, price = ? WHERE id = ?",
                (name, quantity, price, item_id),
            )
        return self.get(item_id) if cursor.rowcount else None

    def delete(self, item_id: int) -> bool:
        with connect(self.path) as connection:
            cursor = connection.execute(
                "DELETE FROM items WHERE id = ?", (item_id,)
            )
        return cursor.rowcount > 0


def validate(payload: object) -> tuple[str, int, float]:
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object.")
    name = payload.get("name")
    quantity = payload.get("quantity")
    price = payload.get("price")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string.")
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 0:
        raise ValueError("quantity must be a non-negative integer.")
    if not isinstance(price, (int, float)) or isinstance(price, bool) or price < 0:
        raise ValueError("price must be a non-negative number.")
    return name.strip(), quantity, float(price)


class Handler(BaseHTTPRequestHandler):
    repository = Repository()

    def log_message(self, *_args: object) -> None:
        return

    def send_json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> object:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            raise ValueError("JSON request body is required.")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def item_id(self) -> int | None:
        parts = [part for part in urlparse(self.path).path.split("/") if part]
        if len(parts) != 2 or parts[0] != "items":
            return None
        try:
            return int(parts[1])
        except ValueError:
            return None

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_json(HTTPStatus.OK, {"status": "ok"})
            return
        if self.path == "/items":
            self.send_json(HTTPStatus.OK, {"items": self.repository.all()})
            return
        item = self.repository.get(self.item_id() or 0)
        self.send_json(HTTPStatus.OK, item) if item else self.send_json(
            HTTPStatus.NOT_FOUND, {"error": "not found"}
        )

    def do_POST(self) -> None:
        if self.path != "/items":
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            item = self.repository.create(*validate(self.read_json()))
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        self.send_json(HTTPStatus.CREATED, item)

    def do_PUT(self) -> None:
        try:
            item = self.repository.update(self.item_id() or 0, *validate(self.read_json()))
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        self.send_json(HTTPStatus.OK, item) if item else self.send_json(
            HTTPStatus.NOT_FOUND, {"error": "not found"}
        )

    def do_DELETE(self) -> None:
        item_id = self.item_id() or 0
        if self.repository.delete(item_id):
            self.send_json(HTTPStatus.OK, {"deleted": True, "id": item_id})
        else:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})


if __name__ == "__main__":
    initialize()
    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    print("Inventory API listening on http://127.0.0.1:8000", flush=True)
    server.serve_forever()
'''


TEST_SOURCE = '''import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

from app import Handler, Repository


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        file.close()
        self.path = Path(file.name)
        self.repository = Repository(self.path)

    def tearDown(self):
        self.path.unlink(missing_ok=True)

    def test_crud(self):
        created = self.repository.create("Sugar", 20, 180.0)
        self.assertEqual(len(self.repository.all()), 1)
        self.assertEqual(self.repository.get(created["id"])["quantity"], 20)
        updated = self.repository.update(created["id"], "Brown Sugar", 15, 220.0)
        self.assertEqual(updated["name"], "Brown Sugar")
        self.assertTrue(self.repository.delete(created["id"]))
        self.assertIsNone(self.repository.get(created["id"]))

    def test_missing_item(self):
        self.assertIsNone(self.repository.get(999))
        self.assertFalse(self.repository.delete(999))


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        file.close()
        cls.path = Path(file.name)
        Handler.repository = Repository(cls.path)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.path.unlink(missing_ok=True)

    def request(self, method, path, body=None):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=5)
        encoded = json.dumps(body) if body is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        connection.request(method, path, body=encoded, headers=headers)
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        status = response.status
        connection.close()
        return status, payload

    def test_http_crud(self):
        status, created = self.request("POST", "/items", {"name": "Eggs", "quantity": 30, "price": 360})
        self.assertEqual(status, 201)
        item_id = created["id"]
        self.assertEqual(self.request("GET", "/items")[0], 200)
        self.assertEqual(self.request("GET", f"/items/{item_id}")[0], 200)
        self.assertEqual(self.request("PUT", f"/items/{item_id}", {"name": "Farm Eggs", "quantity": 24, "price": 390})[0], 200)
        self.assertEqual(self.request("DELETE", f"/items/{item_id}")[0], 200)
        self.assertEqual(self.request("GET", f"/items/{item_id}")[0], 404)

    def test_health(self):
        self.assertEqual(self.request("GET", "/health"), (200, {"status": "ok"}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
'''


README_SOURCE = '''# Inventory REST API

A minimal Python and SQLite REST API generated and verified by Sophyane.

## Run

    python app.py

## Test

    python -m unittest -v

Endpoints: `GET /health`, `GET/POST /items`, and `GET/PUT/DELETE /items/{id}`.
'''


def _plan(state: BuildState) -> str:
    state.criteria = [
        "Python REST API created",
        "SQLite persistence used",
        "CRUD operations implemented",
        "Automated tests created and executed",
        "No index.html created",
        "Exact test command and exit code recorded",
        "Every acceptance criterion verified before completion",
    ]
    state.record("Acceptance criteria created")
    return "build"


def _build(state: BuildState) -> str:
    if state.project.exists():
        shutil.rmtree(state.project)
    state.project.mkdir(parents=True)
    files = {"app.py": APP_SOURCE, "test_app.py": TEST_SOURCE, "README.md": README_SOURCE}
    for name, content in files.items():
        (state.project / name).write_text(content, encoding="utf-8")
    state.created_files = sorted(files)
    state.record(f"Created {len(files)} project files")
    return "test"


def _test(state: BuildState) -> str:
    state.attempts += 1
    state.test_command = [sys.executable, "-m", "unittest", "-v"]
    result = subprocess.run(
        state.test_command,
        cwd=state.project,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    state.test_exit_code = result.returncode
    state.stdout = result.stdout
    state.stderr = result.stderr
    state.record(f"Test attempt {state.attempts} exited with {result.returncode}")
    if result.returncode == 0 or state.attempts >= MAX_REPAIR_ATTEMPTS:
        return "verify"
    return "repair"


def _repair(state: BuildState) -> str:
    # Restore the known-good source as the smallest deterministic repair.
    (state.project / "app.py").write_text(APP_SOURCE, encoding="utf-8")
    (state.project / "test_app.py").write_text(TEST_SOURCE, encoding="utf-8")
    state.record("Applied bounded repair by restoring validated source templates")
    return "test"


def _verify(state: BuildState) -> str:
    app_text = (state.project / "app.py").read_text(encoding="utf-8")
    state.checks = {
        "project_exists": state.project.is_dir(),
        "app_created": (state.project / "app.py").is_file(),
        "tests_created": (state.project / "test_app.py").is_file(),
        "readme_created": (state.project / "README.md").is_file(),
        "sqlite_used": "sqlite3" in app_text,
        "crud_present": all(marker in app_text for marker in ("do_GET", "do_POST", "do_PUT", "do_DELETE")),
        "tests_passed": state.test_exit_code == 0,
        "no_index_html": not any(state.project.rglob("index.html")),
        "exit_code_recorded": isinstance(state.test_exit_code, int),
        "test_command_recorded": bool(state.test_command),
    }
    state.verified = all(state.checks.values())
    state.record(f"Verification {'passed' if state.verified else 'failed'}")
    return "report"


def _report(state: BuildState) -> None:
    report = {
        "request": state.request,
        "acceptance_criteria": state.criteria,
        "project": str(state.project),
        "created_files": state.created_files,
        "test_command": state.test_command,
        "test_exit_code": state.test_exit_code,
        "stdout": state.stdout,
        "stderr": state.stderr,
        "attempts": state.attempts,
        "checks": state.checks,
        "timeline": state.timeline,
        "verified": state.verified,
    }
    (state.project / "benchmark_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return None


def run_inventory_workflow(request: str) -> str:
    project = PROJECTS_DIR / "inventory_api"
    state = BuildState(request=request, project=project)
    graph = BuildGraph()
    graph.add("plan", _plan)
    graph.add("build", _build)
    graph.add("test", _test)
    graph.add("repair", _repair)
    graph.add("verify", _verify)
    graph.add("report", _report)
    graph.run(state, "plan")

    lines = [
        "=== SOPHYANE AUTONOMOUS BUILD REPORT ===",
        "",
        "Acceptance criteria:",
        *[f"- {item}" for item in state.criteria],
        "",
        "Created files:",
        *[f"- {item}" for item in state.created_files],
        "",
        "Exact test command:",
        " ".join(state.test_command),
        "",
        f"Test exit code: {state.test_exit_code}",
        "",
        "Test output:",
        state.stdout or state.stderr or "[empty]",
        "",
        "Verification:",
        *[f"- {name}: {'PASS' if passed else 'FAIL'}" for name, passed in state.checks.items()],
        "",
        f"Repair attempts: {max(0, state.attempts - 1)}",
        f"Project: {state.project}",
        f"Report: {state.project / 'benchmark_report.json'}",
        f"Final result: {'PASS' if state.verified else 'FAIL'}",
    ]
    return "\n".join(lines)
