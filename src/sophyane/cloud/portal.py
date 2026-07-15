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

        if path == "/api/v1/account/me" and method == "GET":
            key = _auth_key(handler)
            principal = self.store.resolve_key(key) if key else None
            if not principal:
                _json(handler, 401, {"ok": False, "error": "invalid API key"})
                return True
            user = self.store.get_user(principal["user_id"]) or {}
            summary = self.store.usage_summary(principal["user_id"])
            _json(
                handler,
                200,
                {
                    "ok": True,
                    "user": {
                        "id": principal["user_id"],
                        "email": principal.get("email"),
                        "name": principal.get("name") or user.get("name"),
                        "plan": principal.get("plan") or user.get("plan"),
                        "email_verified": bool(principal.get("email_verified") or user.get("email_verified")),
                    },
                    "usage": summary,
                    "plans": list_plans(),
                },
            )
            return True

        if path in {"/api/v1/account/plan", "/api/v1/account/upgrade"} and method == "POST":
            key = _auth_key(handler)
            principal = self.store.resolve_key(key) if key else None
            if not principal:
                _json(handler, 401, {"ok": False, "error": "invalid API key"})
                return True
            body = _read_json(handler)
            plan = str(body.get("plan") or "").strip().lower()
            valid = {p["id"] for p in list_plans()}
            if plan not in valid:
                _json(handler, 400, {"ok": False, "error": f"invalid plan; choose one of {sorted(valid)}"})
                return True
            result = self.store.update_plan(principal["user_id"], plan)
            if not result.get("ok"):
                _json(handler, 400, result)
                return True
            _json(
                handler,
                200,
                {
                    **result,
                    "message": f"Plan updated to {plan}. Billing is usage-based; higher plans raise included tokens.",
                    "plans": list_plans(),
                },
            )
            return True

        if path == "/api/v1/chat" and method == "POST":
            key = _auth_key(handler)
            principal = self.store.resolve_key(key) if key else None
            if not principal:
                _json(handler, 401, {"ok": False, "error": "invalid API key — sign in with email OTP first"})
                return True
            body = _read_json(handler)
            message = str(body.get("message") or body.get("prompt") or "").strip()
            if not message:
                _json(handler, 400, {"ok": False, "error": "message required"})
                return True
            # Optional short history for context (list of {role, content})
            history = body.get("history") if isinstance(body.get("history"), list) else []
            edge = bool(body.get("edge"))
            reply = ""
            model_used = "unknown"
            try:
                from sophyane.config import load_config
                from sophyane.main import create_provider

                system = (
                    "You are Sophyane, a helpful AI assistant in a ChatGPT-style chat product. "
                    "Answer the user's actual question directly and specifically. "
                    "Do not dump unrelated product marketing, capability catalogs, or generic harness essays "
                    "unless the user asked about Sophyane itself. "
                    "Be concise, structured, and useful. If you are unsure, say so."
                )
                # Build contextual prompt from recent turns
                ctx_parts: list[str] = []
                for turn in history[-8:]:
                    if not isinstance(turn, dict):
                        continue
                    role = str(turn.get("role") or "user")
                    content = str(turn.get("content") or "").strip()
                    if not content or content == "…":
                        continue
                    ctx_parts.append(f"{role.upper()}: {content[:1500]}")
                ctx_parts.append(f"USER: {message}")
                prompt = "\n".join(ctx_parts)
                if edge:
                    system += (
                        " Prefer answers that work offline/on-device when relevant; "
                        "still answer the question itself first."
                    )

                provider = create_provider(load_config())
                if hasattr(provider, "max_tokens"):
                    try:
                        provider.max_tokens = max(int(getattr(provider, "max_tokens", 512) or 512), 512)
                    except Exception:
                        pass
                reply = provider.generate(prompt, system)
                model_used = str(getattr(provider, "model", None) or load_config().get("model") or "provider")
                # If provider returns empty/boilerplate, fall back carefully
                if not (reply or "").strip():
                    raise RuntimeError("empty provider reply")
            except Exception as error:  # noqa: BLE001
                # Fallback: only use expert pack for harness/engineering-ish prompts
                low = message.lower()
                harnessy = any(
                    k in low
                    for k in (
                        "sophyane",
                        "harness",
                        "agent loop",
                        "mesh",
                        "federat",
                        "lora",
                        "peft",
                        "tool registry",
                    )
                )
                if harnessy:
                    from sophyane.expert.answer import answer_tough_question

                    reply = answer_tough_question(message, mode="expert").get("answer") or str(error)
                    model_used = "expert-pack"
                else:
                    reply = (
                        "I could not reach a live language model just now "
                        f"({error}). Please retry, or run `sophyane --doctor` / ensure local_gguf or API keys are configured."
                    )
                    model_used = "error-fallback"

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
                    "model": model_used,
                    "user": principal.get("email"),
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

        def _content_type(self, target: Path) -> str:
            suffix = target.suffix.lower()
            if suffix == ".css":
                return "text/css; charset=utf-8"
            if suffix == ".js":
                return "application/javascript; charset=utf-8"
            if suffix == ".svg":
                return "image/svg+xml"
            if suffix == ".json":
                return "application/json"
            if suffix in {".webmanifest", ".manifest"}:
                return "application/manifest+json; charset=utf-8"
            if suffix == ".pdf":
                return "application/pdf"
            if suffix in {".gz", ".tgz"}:
                return "application/gzip"
            if suffix == ".sh":
                return "text/x-shellscript; charset=utf-8"
            if suffix == ".ps1":
                return "text/plain; charset=utf-8"
            if suffix == ".txt":
                return "text/plain; charset=utf-8"
            if suffix == ".zip":
                return "application/zip"
            if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico"}:
                return {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".gif": "image/gif",
                    ".webp": "image/webp",
                    ".ico": "image/x-icon",
                }[suffix]
            return "text/html; charset=utf-8"

        def _resolve_static(self, path: str) -> Path | None:
            """Map URL path → site file. None means 404 (do not fake index.html for assets)."""
            rel = "index.html" if path == "/" else path.lstrip("/")
            aliases = {
                "docs": "docs.html",
                "docs/": "docs.html",
                "pricing": "pricing.html",
                "pricing/": "pricing.html",
                "get-api": "get-api.html",
                "get-api/": "get-api.html",
                "api-keys": "get-api.html",
                "login": "get-api.html",
                "signup": "get-api.html",
                "start": "start.html",
                "start/": "start.html",
                "welcome": "start.html",
                "getting-started": "start.html",
                "onboarding": "start.html",
                "browser": "browser.html",
                "browser/": "browser.html",
                "browser-home": "browser-home/index.html",
                "browser-home/": "browser-home/index.html",
            }
            rel = aliases.get(rel, rel)
            target = (site / rel).resolve()
            site_root = site.resolve()
            browser_pkg = (Path(__file__).resolve().parent.parent / "browser" / "home").resolve()
            allowed = str(target).startswith(str(site_root)) or str(target).startswith(str(browser_pkg))
            if not allowed:
                return None
            if target.is_dir():
                index = target / "index.html"
                return index if index.exists() else None
            if target.exists() and target.is_file():
                return target
            # Missing file: never fall back to homepage for asset-like paths
            if Path(rel).suffix:
                return None
            # bare unknown path → homepage only for clean SPA-like nav
            home = site / "index.html"
            return home if home.exists() else None

        def _serve_static(self, *, head_only: bool = False) -> None:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            if path.startswith("/api/"):
                if path == "/api/v1/browser" and not head_only:
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
                                "handbook": "/static/Sophyane_Complete_Handbook.pdf",
                            },
                            "cli": ["sophyane-browser", "sophyane --browser"],
                            "note": (
                                "Download Sophyane Browser for full Chromium profile mode. "
                                "Opening /browser-home/ in a new tab remains supported without install."
                            ),
                        },
                    )
                    return
                if head_only and path == "/api/v1/browser":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    return
                if head_only:
                    # API HEAD: probe existence without body
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    return
                app.handle_api("GET", path, self)
                return

            target = self._resolve_static(path)
            if target is None or not target.exists():
                if head_only:
                    self.send_response(404)
                    self.end_headers()
                    return
                _json(self, 404, {"ok": False, "error": "not found", "path": path})
                return
            data = b"" if head_only else target.read_bytes()
            ctype = self._content_type(target)
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            size = 0 if head_only else len(data)
            if head_only:
                try:
                    size = target.stat().st_size
                except OSError:
                    size = 0
            self.send_header("Content-Length", str(size))
            if target.suffix.lower() in {".gz", ".tgz", ".zip", ".sh", ".ps1"}:
                self.send_header(
                    "Content-Disposition",
                    f'attachment; filename="{target.name}"',
                )
            elif target.suffix.lower() == ".pdf":
                self.send_header(
                    "Content-Disposition",
                    f'inline; filename="{target.name}"',
                )
            self.end_headers()
            if not head_only:
                self.wfile.write(data)

        def do_HEAD(self) -> None:  # noqa: N802
            self._serve_static(head_only=True)

        def do_GET(self) -> None:  # noqa: N802
            self._serve_static(head_only=False)

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
