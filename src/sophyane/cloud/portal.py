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
            _json(
                handler,
                200,
                {
                    "ok": True,
                    "service": "sophyane-cloud",
                    "version": __version__,
                    "auth": "email_otp",
                    "start": "/start.html",
                    "signup": "/get-api.html",
                },
            )
            return True
        if path == "/api/v1/onboarding":
            from sophyane.cloud.email_otp import load_smtp_env

            smtp = load_smtp_env()
            _json(
                handler,
                200,
                {
                    "ok": True,
                    "version": __version__,
                    "product": "Sophyane — cross-platform agentic AI harness",
                    "auth": {
                        "method": "email_otp",
                        "signup_once": True,
                        "otp_from": smtp.get("SMTP_USER") or "badrpk@gmail.com",
                        "otp_ttl_minutes": 10,
                        "steps": [
                            "POST /api/v1/auth/request-otp with email + purpose signup|login",
                            "Check email for 6-digit code",
                            "POST /api/v1/auth/verify-otp with email + otp",
                            "Save sph_ API key shown once",
                        ],
                    },
                    "plans": list_plans(),
                    "pricing_note": COMPETITOR_HINT,
                    "hybrid_note": (
                        "Cloud tokens are ultra-low cost; heavy extra compute can run free "
                        "on user devices via Sophyane mesh / local GGUF."
                    ),
                    "endpoints": {
                        "request_otp": "/api/v1/auth/request-otp",
                        "verify_otp": "/api/v1/auth/verify-otp",
                        "chat": "/api/v1/chat",
                        "usage": "/api/v1/usage",
                        "pricing": "/api/v1/pricing",
                        "health": "/api/v1/health",
                    },
                    "local_ports": {
                        "cloud_portal": 8780,
                        "hardware_api": 8770,
                        "mesh": 8777,
                        "local_gguf": 8766,
                    },
                    "install": "curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | sh",
                    "repo": "https://github.com/badrpk/sophyane",
                    "pages": {
                        "start": "/start.html",
                        "login": "/get-api.html",
                        "pricing": "/pricing.html",
                        "docs": "/docs.html",
                        "browser_download": "/browser.html",
                        "browser_open_tab": "/browser-home/",
                        "handbook_pdf": "/static/Sophyane_Complete_Handbook.pdf",
                    },
                    "browser": {
                        "download_page": "/browser.html",
                        "open_in_new_tab": "/browser-home/",
                        "package": "/download/sophyane-browser.tar.gz",
                        "install_sh": "/download/install-sophyane-browser.sh",
                        "install_ps1": "/download/install-sophyane-browser.ps1",
                        "cli": "sophyane-browser  OR  sophyane --browser",
                        "note": "Download for full Sophyane Browser; new-tab open remains available.",
                    },
                    "capabilities_highlight": [
                        "Plan-act-verify harness + multi-provider fallback",
                        "Skills, RAG, sandboxed REPL, MCP-lite",
                        "Mesh federation + continual C++ PEFT training",
                        "AI Kernel, ERP, app factory, hardware multi-lang API",
                        "SoC appliance boot, browser, self-improve ledger",
                    ],
                    "stats": self.store.stats(),
                    "message": "Read /start.html when you begin — all essentials are listed there.",
                },
            )
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

        # --- Email OTP auth (signup once + login) ---
        if path in {"/api/v1/auth/request-otp", "/api/v1/signup/request-otp"} and method == "POST":
            body = _read_json(handler)
            email = str(body.get("email") or "").strip().lower()
            name = str(body.get("name") or "").strip()
            plan = str(body.get("plan") or "hybrid").strip().lower()
            purpose = str(body.get("purpose") or body.get("mode") or "signup").strip().lower()
            if purpose not in {"signup", "login"}:
                purpose = "signup"
            if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
                _json(handler, 400, {"ok": False, "error": "valid email required"})
                return True
            if plan not in {p["id"] for p in list_plans()}:
                plan = "hybrid"
            created = self.store.create_otp(email, purpose, name=name, plan=plan)
            if not created.get("ok"):
                code = 409 if created.get("code") in {"already_registered", "not_registered"} else 400
                _json(handler, code, created)
                return True
            from sophyane.cloud.email_otp import send_otp_email

            sent = send_otp_email(email, str(created["otp"]), purpose=purpose)
            if not sent.get("ok"):
                _json(handler, 502, {"ok": False, "error": f"failed to send OTP email: {sent.get('error')}"})
                return True
            _json(
                handler,
                200,
                {
                    "ok": True,
                    "email": email,
                    "purpose": purpose,
                    "expires_in": created.get("expires_in"),
                    "message": (
                        f"OTP sent once to {email} from badrpk@gmail.com. "
                        "Enter the 6-digit code to finish "
                        + ("signup and receive your API key." if purpose == "signup" else "login.")
                    ),
                },
            )
            return True

        if path in {"/api/v1/auth/verify-otp", "/api/v1/signup/verify-otp", "/api/v1/login/verify-otp"} and method == "POST":
            body = _read_json(handler)
            email = str(body.get("email") or "").strip().lower()
            otp = str(body.get("otp") or body.get("code") or "").strip()
            purpose = str(body.get("purpose") or body.get("mode") or "signup").strip().lower()
            if purpose not in {"signup", "login"}:
                # path hint
                if "login" in path:
                    purpose = "login"
                else:
                    purpose = "signup"
            verified = self.store.verify_otp(email, otp, purpose)
            if not verified.get("ok"):
                _json(handler, 401, verified)
                return True
            name = str(body.get("name") or verified.get("name") or "").strip()
            plan = str(body.get("plan") or verified.get("plan") or "hybrid").strip().lower()
            if plan not in {p["id"] for p in list_plans()}:
                plan = "hybrid"

            existing = self.store.get_user_by_email(email)
            is_new = existing is None
            if purpose == "signup" or is_new:
                user = self.store.create_user(email, name=name, plan=plan, verified=True)
                self.store.mark_verified_login(user["id"])
                key = self.store.issue_key(user["id"], label="default")
                _json(
                    handler,
                    200,
                    {
                        "ok": True,
                        "auth": "signup",
                        "new_user": True,
                        "user": {
                            "id": user["id"],
                            "email": user["email"],
                            "plan": user.get("plan") or plan,
                            "email_verified": True,
                        },
                        "api_key": key["api_key"],
                        "key_id": key["key_id"],
                        "endpoint": "/api/v1/chat",
                        "docs": "/docs",
                        "message": "Email verified. Welcome to Sophyane Cloud. Save your API key now.",
                        "next": {
                            "start_guide": "/start.html",
                            "docs": "/docs.html",
                            "pricing": "/pricing.html",
                            "chat": "POST /api/v1/chat with Authorization: Bearer <api_key>",
                            "local_install": "curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | sh",
                            "handbook_pdf": "/static/Sophyane_Complete_Handbook.pdf",
                        },
                    },
                )
                return True

            # login: existing verified user — issue a fresh key for this session
            user = existing
            self.store.mark_verified_login(user["id"])
            key = self.store.issue_key(user["id"], label="login")
            _json(
                handler,
                200,
                {
                    "ok": True,
                    "auth": "login",
                    "new_user": False,
                    "user": {
                        "id": user["id"],
                        "email": user["email"],
                        "plan": user.get("plan"),
                        "email_verified": True,
                    },
                    "api_key": key["api_key"],
                    "key_id": key["key_id"],
                    "endpoint": "/api/v1/chat",
                    "message": "Logged in. New API key issued for this session — save it securely.",
                    "next": {
                        "start_guide": "/start.html",
                        "docs": "/docs.html",
                        "chat": "POST /api/v1/chat with Authorization: Bearer <api_key>",
                    },
                },
            )
            return True

        # Legacy signup without OTP — disabled; guide to email OTP
        if path == "/api/v1/signup" and method == "POST":
            body = _read_json(handler)
            _json(
                handler,
                400,
                {
                    "ok": False,
                    "error": "Email OTP required. POST /api/v1/auth/request-otp then /api/v1/auth/verify-otp",
                    "email": body.get("email"),
                    "steps": [
                        "POST /api/v1/auth/request-otp {email, name?, plan?, purpose:'signup'}",
                        "POST /api/v1/auth/verify-otp {email, otp, purpose:'signup'}",
                    ],
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
                # Browser open helper (JSON) + downloads list
                if path == "/api/v1/browser":
                    _json(
                        self,
                        200,
                        {
                            "ok": True,
                            "open_in_new_tab": "/browser-home/",
                            "download_page": "/browser.html",
                            "downloads": {
                                "package": "/download/sophyane-browser.tar.gz",
                                "linux_mac_install": "/download/install-sophyane-browser.sh",
                                "windows_install": "/download/install-sophyane-browser.ps1",
                                "readme": "/download/README.txt",
                            },
                            "cli": ["sophyane-browser", "sophyane --browser"],
                            "note": (
                                "Download Sophyane Browser for full Chromium profile mode. "
                                "Opening /browser-home/ in a new tab remains supported without install."
                            ),
                        },
                    )
                    return
                app.handle_api("GET", path, self)
                return
            # static site
            rel = "index.html" if path == "/" else path.lstrip("/")
            # docs alias
            if rel in {"docs", "docs/"}:
                rel = "docs.html"
            if rel in {"pricing", "pricing/"}:
                rel = "pricing.html"
            if rel in {"get-api", "get-api/", "api-keys", "login", "signup"}:
                rel = "get-api.html"
            if rel in {"start", "start/", "welcome", "getting-started", "onboarding"}:
                rel = "start.html"
            if rel in {"browser", "browser/"}:
                rel = "browser.html"
            # directory index for browser-home
            if rel in {"browser-home", "browser-home/"}:
                rel = "browser-home/index.html"
            target = (site / rel).resolve()
            site_root = site.resolve()
            # allow resolved symlink targets under site or browser package home
            browser_pkg = (Path(__file__).resolve().parent.parent / "browser" / "home").resolve()
            allowed = str(target).startswith(str(site_root)) or str(target).startswith(str(browser_pkg))
            if not allowed or not target.exists():
                if target.is_dir():
                    index = target / "index.html"
                    if index.exists():
                        target = index
                    else:
                        target = site / "index.html"
                elif not target.exists() or not target.is_file():
                    target = site / "index.html"
            if target.is_dir():
                target = target / "index.html"
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
            elif target.suffix == ".pdf":
                ctype = "application/pdf"
            elif target.suffix in {".gz", ".tgz"}:
                ctype = "application/gzip"
            elif target.suffix == ".sh":
                ctype = "text/x-shellscript; charset=utf-8"
            elif target.suffix == ".ps1":
                ctype = "text/plain; charset=utf-8"
            elif target.suffix == ".txt":
                ctype = "text/plain; charset=utf-8"
            elif target.suffix == ".zip":
                ctype = "application/zip"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            if target.suffix in {".gz", ".tgz", ".zip", ".sh", ".ps1"}:
                self.send_header(
                    "Content-Disposition",
                    f'attachment; filename="{target.name}"',
                )
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
