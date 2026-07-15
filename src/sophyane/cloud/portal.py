"""HTTP portal: marketing site + public API token endpoints (stdlib)."""

from __future__ import annotations

import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from sophyane.cloud.pricing import COMPETITOR_HINT, estimate_cost, list_plans
from sophyane.cloud.store import PortalStore
from sophyane.version import __version__

SITE_DIR_CANDIDATES = [
    Path.home() / ".local/share/sophyane/current/website",
    Path(__file__).resolve().parents[3] / "website",
]


def _site_dir() -> Path:
    for p in SITE_DIR_CANDIDATES:
        if p.exists():
            return p
    p = SITE_DIR_CANDIDATES[0]
    p.mkdir(parents=True, exist_ok=True)
    return p


def _json(handler: BaseHTTPRequestHandler, code: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    raw = handler.rfile.read(length) if length else b"{}"
    try:
        data = json.loads(raw.decode("utf-8") or "{}")
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _auth_key(handler: BaseHTTPRequestHandler) -> str:
    auth = handler.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (handler.headers.get("X-API-Key") or "").strip()


class PortalApp:
    def __init__(self) -> None:
        self.store = PortalStore()
        self.site = _site_dir()

    def handle_api(self, method: str, path: str, handler: BaseHTTPRequestHandler) -> bool:
        if method == "OPTIONS":
            _json(handler, 204, {})
            return True

        if path == "/api/v1/health":
            _json(handler, 200, {"ok": True, "service": "sophyane-cloud", "version": __version__})
            return True
        if path == "/api/v1/pricing":
            _json(
                handler,
                200,
                {
                    "ok": True,
                    "plans": list_plans(),
                    "comparison": COMPETITOR_HINT,
                    "hybrid_note": (
                        "Use Hybrid Edge: pay near-zero for cloud orchestration; "
                        "run heavy inference on your own Sophyane-installed devices for free extra compute."
                    ),
                },
            )
            return True
        if path == "/api/v1/stats":
            _json(handler, 200, {"ok": True, **self.store.stats()})
            return True

        if path == "/api/v1/signup" and method == "POST":
            body = _read_json(handler)
            email = str(body.get("email") or "").strip().lower()
            name = str(body.get("name") or "").strip()
            plan = str(body.get("plan") or "free").strip().lower()
            if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
                _json(handler, 400, {"ok": False, "error": "valid email required"})
                return True
            if plan not in {p["id"] for p in list_plans()}:
                plan = "free"
            user = self.store.create_user(email, name=name, plan=plan)
            key = self.store.issue_key(user["id"], label="default")
            _json(
                handler,
                200,
                {
                    "ok": True,
                    "user": {"id": user["id"], "email": user["email"], "plan": user["plan"]},
                    "api_key": key["api_key"],
                    "key_id": key["key_id"],
                    "endpoint": "/api/v1/chat",
                    "docs": "/docs",
                    "message": "Welcome to Sophyane Cloud. Save your API key securely.",
                },
            )
            return True

        if path == "/api/v1/keys" and method == "POST":
            key = _auth_key(handler)
            principal = self.store.resolve_key(key) if key else None
            if not principal:
                _json(handler, 401, {"ok": False, "error": "invalid API key"})
                return True
            body = _read_json(handler)
            issued = self.store.issue_key(principal["user_id"], label=str(body.get("label") or "extra"))
            _json(handler, 200, issued)
            return True

        if path == "/api/v1/usage" and method == "GET":
            key = _auth_key(handler)
            principal = self.store.resolve_key(key) if key else None
            if not principal:
                _json(handler, 401, {"ok": False, "error": "invalid API key"})
                return True
            summary = self.store.usage_summary(principal["user_id"])
            cost = estimate_cost(summary["tokens"], principal.get("plan") or "free")
            _json(handler, 200, {"ok": True, "usage": summary, "estimate": cost, "plan": principal.get("plan")})
            return True

        if path == "/api/v1/chat" and method == "POST":
            key = _auth_key(handler)
            principal = self.store.resolve_key(key) if key else None
            if not principal:
                _json(handler, 401, {"ok": False, "error": "invalid API key — signup at /api/v1/signup"})
                return True
            body = _read_json(handler)
            message = str(body.get("message") or body.get("prompt") or "").strip()
            if not message:
                _json(handler, 400, {"ok": False, "error": "message required"})
                return True
            # Prefer local/expert hybrid so portal works without paid frontier keys
            reply = ""
            try:
                use_edge = bool(body.get("edge") or principal.get("plan") == "hybrid")
                if use_edge:
                    from sophyane.expert.answer import answer_tough_question

                    reply = answer_tough_question(message, mode="expert").get("answer") or ""
                    reply = (
                        "[Hybrid Edge] Heavy compute preferred on your devices via Sophyane mesh/local GGUF.\n\n"
                        + reply
                    )
                else:
                    from sophyane.config import load_config
                    from sophyane.main import create_provider

                    provider = create_provider(load_config())
                    reply = provider.generate(
                        message,
                        "You are Sophyane Cloud — a helpful, investor-grade AI agent harness assistant. Be clear and actionable.",
                    )
            except Exception as error:  # noqa: BLE001
                from sophyane.expert.answer import answer_tough_question

                reply = answer_tough_question(message, mode="expert").get("answer") or str(error)
                reply = f"[fallback expert pack] {reply}"

            # crude token estimate
            tokens = max(1, (len(message) + len(reply)) // 4)
            self.store.record_usage(principal["user_id"], tokens, key_id=principal["key_id"], endpoint="/api/v1/chat")
            _json(
                handler,
                200,
                {
                    "ok": True,
                    "reply": reply,
                    "usage": {"tokens_estimate": tokens},
                    "plan": principal.get("plan"),
                    "model": "sophyane-cloud",
                    "version": __version__,
                },
            )
            return True

        if path.startswith("/api/"):
            _json(handler, 404, {"ok": False, "error": "not found", "path": path})
            return True
        return False


def create_portal_app() -> PortalApp:
    return PortalApp()


def serve_portal(host: str = "0.0.0.0", port: int = 8780) -> ThreadingHTTPServer:
    app = create_portal_app()
    site = app.site

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def do_OPTIONS(self) -> None:  # noqa: N802
            app.handle_api("OPTIONS", urlparse(self.path).path, self)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            if path.startswith("/api/"):
                app.handle_api("GET", path, self)
                return
            # static site
            rel = "index.html" if path == "/" else path.lstrip("/")
            # docs alias
            if rel in {"docs", "docs/"}:
                rel = "docs.html"
            if rel in {"pricing", "pricing/"}:
                rel = "pricing.html"
            if rel in {"get-api", "get-api/", "api-keys"}:
                rel = "get-api.html"
            target = (site / rel).resolve()
            if not str(target).startswith(str(site.resolve())) or not target.exists() or not target.is_file():
                # SPA fallback
                target = site / "index.html"
            if not target.exists():
                _json(self, 404, {"ok": False, "error": "site not built"})
                return
            data = target.read_bytes()
            ctype = "text/html; charset=utf-8"
            if target.suffix == ".css":
                ctype = "text/css; charset=utf-8"
            elif target.suffix == ".js":
                ctype = "application/javascript; charset=utf-8"
            elif target.suffix == ".svg":
                ctype = "image/svg+xml"
            elif target.suffix == ".json":
                ctype = "application/json"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path.rstrip("/") or "/"
            if not app.handle_api("POST", path, self):
                _json(self, 404, {"ok": False, "error": "not found"})

    server = ThreadingHTTPServer((host, port), Handler)
    return server


def serve_portal_background(host: str = "0.0.0.0", port: int = 8780) -> dict[str, Any]:
    try:
        server = serve_portal(host, port)
    except OSError as error:
        if "Address already in use" in str(error):
            return {"ok": True, "reused": True, "port": port, "note": str(error)}
        raise
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return {
        "ok": True,
        "host": host,
        "port": port,
        "url": f"http://{host}:{port}/",
        "api": f"http://{host}:{port}/api/v1/health",
        "version": __version__,
    }
