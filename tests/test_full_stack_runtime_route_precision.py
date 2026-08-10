from __future__ import annotations

from pathlib import Path

from sophyane.full_stack_runtime import (
    discover_api_endpoints,
)


def _pairs(
    root: Path,
) -> set[
    tuple[str, str]
]:
    return {
        (
            item.method,
            item.path,
        )
        for item in discover_api_endpoints(
            root
        )
    }


def test_exact_path_comparison_is_endpoint(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.py").write_text(
        r'''
from http.server import BaseHTTPRequestHandler

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/projects":
            return
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    assert (
        "GET",
        "/api/projects",
    ) in _pairs(
        tmp_path
    )


def test_membership_routes_are_endpoints(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.py").write_text(
        r'''
from http.server import BaseHTTPRequestHandler

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]

        if path in {
            "/api/projects",
            "/api/tasks",
            "/api/stats",
        }:
            return
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    assert _pairs(
        tmp_path
    ) == {
        (
            "GET",
            "/api/projects",
        ),
        (
            "GET",
            "/api/tasks",
        ),
        (
            "GET",
            "/api/stats",
        ),
    }


def test_startswith_prefix_is_not_false_endpoint(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.py").write_text(
        r'''
from http.server import BaseHTTPRequestHandler

class Handler(BaseHTTPRequestHandler):
    def do_DELETE(self):
        if self.path.startswith("/api/tasks/"):
            route = "/api/tasks/{id}"
            return
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    pairs = _pairs(
        tmp_path
    )

    assert (
        "DELETE",
        "/api/tasks/{id}",
    ) in pairs

    assert (
        "DELETE",
        "/api/tasks/",
    ) not in pairs


def test_unrelated_handler_literal_is_not_route(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.py").write_text(
        r'''
from http.server import BaseHTTPRequestHandler

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        documentation = "/api/not-real"

        if self.path == "/api/tasks":
            return
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    pairs = _pairs(
        tmp_path
    )

    assert (
        "POST",
        "/api/tasks",
    ) in pairs

    assert (
        "POST",
        "/api/not-real",
    ) not in pairs


def test_parameterized_literal_without_grounding_is_not_route(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.py").write_text(
        r'''
from http.server import BaseHTTPRequestHandler

class Handler(BaseHTTPRequestHandler):
    def do_PUT(self):
        docs = "/api/tasks/{id}"
        return
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    assert _pairs(
        tmp_path
    ) == set()


def test_parameterized_template_matches_prefix(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.py").write_text(
        r'''
from http.server import BaseHTTPRequestHandler

class Handler(BaseHTTPRequestHandler):
    def do_PUT(self):
        path = self.path.split("?", 1)[0]

        if path.startswith("/api/tasks/"):
            route = "/api/tasks/{id}"
            return
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    assert _pairs(
        tmp_path
    ) == {
        (
            "PUT",
            "/api/tasks/{id}",
        ),
    }


def test_wrong_template_family_is_not_attached(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.py").write_text(
        r'''
from http.server import BaseHTTPRequestHandler

class Handler(BaseHTTPRequestHandler):
    def do_DELETE(self):
        if self.path.startswith("/api/tasks/"):
            docs = "/api/users/{id}"
            return
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    assert _pairs(
        tmp_path
    ) == set()


def test_method_scope_remains_preserved(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.py").write_text(
        r'''
from http.server import BaseHTTPRequestHandler

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/api/create":
            return
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    pairs = _pairs(
        tmp_path
    )

    assert (
        "POST",
        "/api/create",
    ) in pairs

    assert (
        "GET",
        "/api/create",
    ) not in pairs
