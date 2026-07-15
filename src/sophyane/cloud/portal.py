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
    # Prefer package-adjacent website (this release tree), then "current" install.
    Path(__file__).resolve().parents[3] / "website",
    Path.home() / ".local/share/sophyane/current/website",
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

        # —— Voice / media (YouTube play by spoken query) ——
        if path in {"/api/v1/media/youtube", "/api/v1/youtube"} and method == "POST":
            body = _read_json(handler)
            query = str(body.get("query") or body.get("q") or body.get("message") or "").strip()
            if not query:
                _json(handler, 400, {"ok": False, "error": "query required"})
                return True
            from sophyane.media_voice import youtube_search

            result = youtube_search(query, limit=int(body.get("limit") or 5))
            _json(handler, 200, result)
            return True

        if path == "/api/v1/voice/intent" and method == "POST":
            body = _read_json(handler)
            text = str(body.get("text") or body.get("message") or "").strip()
            from sophyane.media_voice import parse_voice_media_intent, youtube_search

            intent = parse_voice_media_intent(text)
            if not intent:
                _json(handler, 200, {"ok": True, "intent": "chat", "text": text})
                return True
            if intent.get("intent") == "youtube_play":
                yt = youtube_search(str(intent.get("query") or ""), limit=5)
                _json(
                    handler,
                    200,
                    {
                        "ok": True,
                        **intent,
                        "youtube": yt,
                        "speak": f"Playing {intent.get('query')} on YouTube.",
                    },
                )
                return True
            if intent.get("intent") == "web_search":
                _json(
                    handler,
                    200,
                    {
                        "ok": True,
                        **intent,
                        "speak": f"Searching for {intent.get('query')}.",
                    },
                )
                return True
            _json(handler, 200, {"ok": True, **intent})
            return True

        # —— Hardware-fit local LLM (recommend → approve → download) ——
        if path in {"/api/v1/local", "/api/v1/local/status", "/api/v1/hardware-fit"} and method == "GET":
            from sophyane.hardware_fit import hardware_fit_status

            _json(handler, 200, hardware_fit_status())
            return True

        if path in {"/api/v1/local/mode", "/api/v1/hardware-fit/mode"} and method == "POST":
            body = _read_json(handler)
            from sophyane.hardware_fit import set_mode

            prefer = body.get("prefer_api_only")
            local_en = body.get("local_enabled")
            result = set_mode(
                prefer_api_only=bool(prefer) if prefer is not None else None,
                local_enabled=bool(local_en) if local_en is not None else None,
            )
            _json(handler, 200, result)
            return True

        if path in {"/api/v1/local/approve", "/api/v1/hardware-fit/approve"} and method == "POST":
            body = _read_json(handler)
            from sophyane.hardware_fit import approve_and_install

            key = str(body.get("model_key") or body.get("key") or "").strip()
            background = bool(body.get("background", True))
            result = approve_and_install(key, background=background)
            code = 200 if result.get("ok") else 400
            _json(handler, code, result)
            return True

        if path in {"/api/v1/local/decline", "/api/v1/hardware-fit/decline"} and method == "POST":
            body = _read_json(handler)
            from sophyane.hardware_fit import decline_offer

            _json(handler, 200, decline_offer(str(body.get("model_key") or body.get("key") or "")))
            return True

        if path in {"/api/v1/local/download", "/api/v1/hardware-fit/download"} and method == "GET":
            from sophyane.hardware_fit import download_status

            _json(handler, 200, {"ok": True, "download": download_status()})
            return True

        # —— LLM provider catalog (top 10 + API keys + free local fallback) ——
        if path in {"/api/v1/llm", "/api/v1/llm/catalog"} and method == "GET":
            from sophyane.llm_catalog import catalog_status

            _json(handler, 200, catalog_status())
            return True

        if path in {"/api/v1/llm/select", "/api/v1/llm/activate"} and method == "POST":
            # Optional auth: signed-in users preferred; still allow local host configure
            body = _read_json(handler)
            from sophyane.llm_catalog import apply_llm_selection

            result = apply_llm_selection(
                provider=str(body.get("provider") or ""),
                model=str(body.get("model") or ""),
                api_key=str(body.get("api_key") or body.get("key") or ""),
                set_fallback=bool(body.get("set_fallback", True)),
            )
            code = 200 if result.get("ok") else 400
            _json(handler, code, result)
            return True

        if path == "/api/v1/llm/key" and method == "POST":
            body = _read_json(handler)
            provider = str(body.get("provider") or "").strip().lower()
            api_key = str(body.get("api_key") or body.get("key") or "").strip()
            if not provider or not api_key:
                _json(handler, 400, {"ok": False, "error": "provider and api_key required"})
                return True
            from sophyane.llm_catalog import apply_llm_selection, catalog_status, resolve_plugin_id
            from sophyane.config import save_secret

            plugin = resolve_plugin_id(provider)
            save_id = "openrouter" if provider == "mistral" else plugin
            save_secret(save_id, api_key)
            _json(
                handler,
                200,
                {
                    "ok": True,
                    "message": f"API key saved for {provider} (stored as {save_id}). Select a model to activate.",
                    "status": catalog_status(),
                },
            )
            return True

        if path in {"/api/v1/llm/key/clear", "/api/v1/llm/clear-key"} and method == "POST":
            body = _read_json(handler)
            from sophyane.llm_catalog import clear_provider_key

            _json(handler, 200, clear_provider_key(str(body.get("provider") or "")))
            return True

        # Same-origin tool proxies for browser-home (avoids Failed to fetch on :8770/:8777)
        if path.startswith("/api/v1/tools/") and method == "GET":
            tool = path.rsplit("/", 1)[-1].strip().lower()
            try:
                if tool == "train":
                    from sophyane.continual.engine import train_status

                    _json(handler, 200, {"ok": True, "tool": "train", "result": train_status()})
                    return True
                if tool == "platform":
                    from sophyane.platform_probe import probe_platform

                    _json(handler, 200, {"ok": True, "tool": "platform", "result": probe_platform().to_dict()})
                    return True
                if tool == "hardware":
                    from sophyane.hardware_registry import hardware_compatibility_report

                    _json(handler, 200, {"ok": True, "tool": "hardware", "result": hardware_compatibility_report()})
                    return True
                if tool == "mesh":
                    try:
                        import urllib.request

                        with urllib.request.urlopen("http://127.0.0.1:8777/v1/mesh/hello", timeout=3.0) as resp:
                            mesh_body = json.loads(resp.read().decode("utf-8"))
                        _json(handler, 200, {"ok": True, "tool": "mesh", "result": mesh_body})
                    except Exception as mesh_err:  # noqa: BLE001
                        _json(
                            handler,
                            200,
                            {
                                "ok": False,
                                "tool": "mesh",
                                "error": str(mesh_err),
                                "hint": "Start mesh: sophyane --mesh-serve (port 8777)",
                            },
                        )
                    return True
                if tool == "usage":
                    key = _auth_key(handler)
                    principal = self.store.resolve_key(key) if key else None
                    if not principal:
                        _json(handler, 401, {"ok": False, "error": "invalid API key — sign in first"})
                        return True
                    summary = self.store.usage_summary(principal["user_id"])
                    cost = estimate_cost(summary["tokens"], principal.get("plan") or "free")
                    _json(
                        handler,
                        200,
                        {"ok": True, "tool": "usage", "result": {"usage": summary, "estimate": cost, "plan": principal.get("plan")}},
                    )
                    return True
                _json(handler, 404, {"ok": False, "error": f"unknown tool: {tool}"})
            except Exception as error:  # noqa: BLE001
                _json(handler, 200, {"ok": False, "tool": tool, "error": str(error)})
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
            # Paid plans → Stripe Checkout (unless force_free for internal)
            from sophyane.cloud.pricing import PLANS
            from sophyane.cloud.stripe_billing import create_checkout_session, stripe_configured

            price = float((PLANS.get(plan) or {}).get("price_usd_month") or 0)
            force_free = bool(body.get("force_free") or body.get("skip_payment"))
            if price > 0 and stripe_configured() and not force_free:
                origin = (handler.headers.get("Origin") or "").rstrip("/")
                if not origin:
                    host = handler.headers.get("Host") or "127.0.0.1:8780"
                    origin = f"http://{host}"
                success = f"{origin}/browser-home/?paid=1&session_id={{CHECKOUT_SESSION_ID}}"
                cancel = f"{origin}/browser-home/?paid=0"
                try:
                    session = create_checkout_session(
                        plan_id=plan,
                        user_id=str(principal["user_id"]),
                        email=str(principal.get("email") or ""),
                        success_url=success,
                        cancel_url=cancel,
                    )
                except Exception as error:  # noqa: BLE001
                    _json(handler, 502, {"ok": False, "error": str(error)})
                    return True
                _json(
                    handler,
                    200,
                    {
                        **session,
                        "checkout": True,
                        "message": f"Redirect to Stripe to pay for {plan}.",
                    },
                )
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
                    "checkout": False,
                    "message": f"Plan updated to {plan}. Billing is usage-based; higher plans raise included tokens.",
                    "plans": list_plans(),
                },
            )
            return True

        if path == "/api/v1/billing/config" and method == "GET":
            from sophyane.cloud.stripe_billing import public_config as stripe_public
            from sophyane.cloud.crypto_billing import public_config as crypto_public
            from sophyane.cloud.payments_rails import public_config as rails_public

            stripe_cfg = stripe_public()
            crypto_cfg = crypto_public()
            rails_cfg = rails_public()
            _json(
                handler,
                200,
                {
                    **stripe_cfg,
                    "crypto": crypto_cfg,
                    "rails": rails_cfg,
                    "methods": {
                        "card_stripe": bool(stripe_cfg.get("enabled")),
                        "crypto": bool(crypto_cfg.get("enabled")),
                        "pk_wallets": any(
                            m.get("rail") in {"jazzcash", "easypaisa", "upaisa"}
                            for m in (rails_cfg.get("methods") or [])
                        ),
                        "exchanges": any(
                            m.get("rail") in {"coinbase", "binance"}
                            for m in (rails_cfg.get("methods") or [])
                            if not m.get("needs_setup")
                        ),
                    },
                },
            )
            return True

        if path == "/api/v1/billing/crypto/config" and method == "GET":
            from sophyane.cloud.crypto_billing import public_config

            _json(handler, 200, public_config())
            return True

        if path == "/api/v1/billing/rails" and method == "GET":
            from sophyane.cloud.payments_rails import public_config as rails_public

            _json(handler, 200, rails_public())
            return True

        if path == "/api/v1/billing/crypto/invoice" and method == "POST":
            key = _auth_key(handler)
            principal = self.store.resolve_key(key) if key else None
            if not principal:
                _json(handler, 401, {"ok": False, "error": "invalid API key — sign in first"})
                return True
            body = _read_json(handler)
            # Multi-rail: PK wallets / Coinbase / Binance via payments_rails; crypto via crypto_billing
            method_name = str(body.get("method") or "monero").strip().lower()
            if method_name in {
                "jazzcash",
                "easypaisa",
                "upaisa",
            } or method_name.startswith(("coinbase", "binance")):
                from sophyane.cloud.payments_rails import create_invoice
            else:
                from sophyane.cloud.crypto_billing import create_invoice

            inv = create_invoice(
                user_id=str(principal["user_id"]),
                email=str(principal.get("email") or ""),
                plan_id=str(body.get("plan") or "").strip().lower(),
                method=method_name,
            )
            code = 200 if inv.get("ok") else 400
            _json(handler, code, inv)
            return True

        if path == "/api/v1/billing/crypto/confirm" and method == "POST":
            key = _auth_key(handler)
            principal = self.store.resolve_key(key) if key else None
            if not principal:
                _json(handler, 401, {"ok": False, "error": "invalid API key"})
                return True
            body = _read_json(handler)
            inv_id = str(body.get("invoice_id") or "").strip()
            txid = str(body.get("txid") or body.get("tx_hash") or body.get("reference") or "").strip()
            if inv_id.startswith("pay_"):
                from sophyane.cloud.payments_rails import get_invoice, user_report_payment
            else:
                from sophyane.cloud.crypto_billing import get_invoice, user_report_payment

            inv = get_invoice(inv_id)
            if not inv:
                _json(handler, 404, {"ok": False, "error": "invoice not found"})
                return True
            result = user_report_payment(inv_id, str(principal["user_id"]), txid=txid)
            if result.get("ok") and (result.get("plan") or (result.get("invoice") or {}).get("status") == "paid"):
                plan = result.get("plan") or (result.get("invoice") or {}).get("plan")
                if plan and (result.get("invoice") or {}).get("status") == "paid":
                    up = self.store.update_plan(principal["user_id"], str(plan))
                    _json(
                        handler,
                        200,
                        {
                            **result,
                            "activated": True,
                            "user": up.get("user"),
                            "message": f"Payment confirmed. Plan set to {plan}.",
                            "plans": list_plans(),
                        },
                    )
                    return True
            _json(handler, 200, result)
            return True

        if path.startswith("/api/v1/billing/crypto/invoice/") and method == "GET":
            inv_id = path.rsplit("/", 1)[-1]
            if inv_id.startswith("pay_"):
                from sophyane.cloud.payments_rails import get_invoice

                inv = get_invoice(inv_id)
            else:
                from sophyane.cloud.crypto_billing import get_invoice, try_auto_confirm_monero

                inv = get_invoice(inv_id)
                if inv and inv.get("status") == "pending" and inv.get("asset") == "XMR":
                    try_auto_confirm_monero(inv_id)
                    inv = get_invoice(inv_id) or inv
            if not inv:
                _json(handler, 404, {"ok": False, "error": "not found"})
                return True
            _json(handler, 200, {"ok": True, "invoice": inv})
            return True

        if path == "/api/v1/billing/payout" and method == "POST":
            key = _auth_key(handler)
            principal = self.store.resolve_key(key) if key else None
            if not principal:
                _json(handler, 401, {"ok": False, "error": "invalid API key"})
                return True
            body = _read_json(handler)
            from sophyane.cloud.payments_rails import create_payout

            result = create_payout(
                user_id=str(principal["user_id"]),
                rail=str(body.get("rail") or body.get("method") or "").strip().lower(),
                amount=float(body.get("amount") or 0),
                currency=str(body.get("currency") or "PKR"),
                destination=str(body.get("destination") or body.get("to") or "").strip(),
                note=str(body.get("note") or ""),
            )
            code = 200 if result.get("ok") else 400
            _json(handler, code, result)
            return True

        if path == "/api/v1/billing/checkout" and method == "POST":
            key = _auth_key(handler)
            principal = self.store.resolve_key(key) if key else None
            if not principal:
                _json(handler, 401, {"ok": False, "error": "invalid API key — sign in first"})
                return True
            body = _read_json(handler)
            plan = str(body.get("plan") or "").strip().lower()
            from sophyane.cloud.stripe_billing import create_checkout_session, stripe_configured

            if not stripe_configured():
                _json(handler, 503, {"ok": False, "error": "Stripe not configured on server"})
                return True
            origin = (handler.headers.get("Origin") or "").rstrip("/")
            if not origin:
                host = handler.headers.get("Host") or "127.0.0.1:8780"
                origin = f"http://{host}"
            success = str(body.get("success_url") or f"{origin}/browser-home/?paid=1&session_id={{CHECKOUT_SESSION_ID}}")
            cancel = str(body.get("cancel_url") or f"{origin}/browser-home/?paid=0")
            try:
                session = create_checkout_session(
                    plan_id=plan,
                    user_id=str(principal["user_id"]),
                    email=str(principal.get("email") or ""),
                    success_url=success,
                    cancel_url=cancel,
                )
            except Exception as error:  # noqa: BLE001
                _json(handler, 502, {"ok": False, "error": str(error)})
                return True
            code = 200 if session.get("ok") else 400
            _json(handler, code, session)
            return True

        if path == "/api/v1/billing/confirm" and method == "POST":
            key = _auth_key(handler)
            principal = self.store.resolve_key(key) if key else None
            if not principal:
                _json(handler, 401, {"ok": False, "error": "invalid API key"})
                return True
            body = _read_json(handler)
            session_id = str(body.get("session_id") or "").strip()
            if not session_id:
                _json(handler, 400, {"ok": False, "error": "session_id required"})
                return True
            from sophyane.cloud.stripe_billing import confirm_session

            try:
                confirmed = confirm_session(session_id, str(principal["user_id"]))
            except Exception as error:  # noqa: BLE001
                _json(handler, 502, {"ok": False, "error": str(error)})
                return True
            if not confirmed.get("ok"):
                _json(handler, 400, confirmed)
                return True
            result = self.store.update_plan(principal["user_id"], str(confirmed["plan"]))
            _json(
                handler,
                200,
                {
                    **result,
                    "paid": True,
                    "plan": confirmed.get("plan"),
                    "session_id": session_id,
                    "message": f"Payment confirmed. Plan set to {confirmed.get('plan')}.",
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
            want_search = body.get("web_search")
            if want_search is None:
                force_search = False
            else:
                force_search = bool(want_search)
            reply = ""
            model_used = "unknown"
            sources: list[dict[str, Any]] = []
            search_meta: dict[str, Any] = {}

            # Instant answers for trivial math (avoid slow local LLM hangs)
            trivial = re.search(
                r"(?:what\s+is|calculate|compute)?\s*(\d+)\s*([+\-*/x×])\s*(\d+)",
                message.lower(),
            )
            if trivial:
                a, op, b = int(trivial.group(1)), trivial.group(2), int(trivial.group(3))
                ops = {"+": a + b, "-": a - b, "*": a * b, "x": a * b, "×": a * b, "/": (a / b if b else "undefined")}
                val = ops.get(op)
                if val is not None:
                    reply = str(int(val) if isinstance(val, float) and val == int(val) else val)
                    model_used = "instant"
                    tokens = max(1, (len(message) + len(reply)) // 4)
                    self.store.record_usage(
                        principal["user_id"], tokens, key_id=principal["key_id"], endpoint="/api/v1/chat"
                    )
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
                            "sources": [],
                            "web_search": False,
                        },
                    )
                    return True

            try:
                from sophyane.config import load_config
                from sophyane.main import create_provider
                from sophyane.web_intel import (
                    format_search_context,
                    grounded_answer_from_search,
                    needs_web_research,
                    web_search,
                )

                system = (
                    "You are Sophyane, a helpful AI assistant with live internet research. "
                    "Answer the user's actual question directly and specifically. "
                    "When LIVE INTERNET RESEARCH is provided, treat it as ground truth — "
                    "prefer it over your own memory (small models often confuse people/places). "
                    "Cite sources briefly. Do not invent biographies. "
                    "Do not dump unrelated product marketing or harness essays "
                    "unless the user asked about Sophyane itself. "
                    "Be concise, structured, and useful."
                )
                # Live web search for factual / "who is" questions.
                # want_search True → always; None → auto heuristic; False → off.
                # Edge mode no longer disables search (user still wants correct facts).
                if want_search is True:
                    do_search = True
                elif want_search is False and not force_search:
                    do_search = False
                else:
                    do_search = force_search or needs_web_research(message)
                research_block = ""
                grounded = ""
                search_meta: dict[str, Any] = {}
                if do_search:
                    try:
                        search_meta = web_search(message, limit=6)
                        research_block = format_search_context(search_meta)
                        grounded = grounded_answer_from_search(message, search_meta)
                        for hit in search_meta.get("results") or []:
                            sources.append(
                                {
                                    "title": hit.get("title"),
                                    "url": hit.get("url"),
                                    "source": hit.get("source"),
                                }
                            )
                    except Exception as search_err:  # noqa: BLE001
                        search_meta = {"ok": False, "error": str(search_err), "results": []}

                cfg = load_config()
                provider_id = str(cfg.get("provider") or "local_gguf").strip().lower()
                local_tier = provider_id in {"local_gguf", "ollama", ""}

                # Prefer live research whenever we have a grounded extract —
                # tiny local models invent wrong biographies (e.g. "actor" for Imran Khan).
                factual = bool(do_search or needs_web_research(message))
                if grounded and factual:
                    # Always use web extract for factual Qs when available (cloud can refine later)
                    reply = grounded
                    model_used = "web-grounded"
                else:
                    # Build contextual prompt from recent turns
                    ctx_parts: list[str] = []
                    if research_block:
                        ctx_parts.append(research_block)
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

                    provider = create_provider(cfg)
                    if hasattr(provider, "max_tokens"):
                        try:
                            provider.max_tokens = max(int(getattr(provider, "max_tokens", 512) or 512), 512)
                        except Exception:
                            pass
                    # Bound LLM wait so chat never hangs 2+ minutes on broken/local models
                    import concurrent.futures

                    llm_timeout = 15 if local_tier else 45
                    try:
                        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                            fut = pool.submit(provider.generate, prompt, system)
                            reply = fut.result(timeout=llm_timeout)
                    except concurrent.futures.TimeoutError:
                        # Never hang the UI — try web, else short error
                        try:
                            if not grounded:
                                search_meta = web_search(message, limit=5)
                                grounded = grounded_answer_from_search(message, search_meta)
                                sources = [
                                    {
                                        "title": h.get("title"),
                                        "url": h.get("url"),
                                        "source": h.get("source"),
                                    }
                                    for h in (search_meta.get("results") or [])
                                ]
                        except Exception:
                            pass
                        if grounded:
                            reply = grounded
                            model_used = "web-grounded (llm-timeout)"
                        else:
                            reply = (
                                f"Model timed out after {llm_timeout}s. "
                                "Open **Models** to pick a cloud API (OpenAI/Claude/Gemini/Grok), "
                                "or keep **Web search** on for factual questions."
                            )
                            model_used = "timeout-fallback"
                    else:
                        model_used = str(
                            getattr(provider, "model", None) or cfg.get("model") or "provider"
                        )
                        if not (reply or "").strip():
                            raise RuntimeError("empty provider reply")

                    # Prefer grounded research when model is weak/wrong vs sources
                    if sources and search_meta.get("ok") and grounded:
                        low_reply = (reply or "").lower()
                        primary_low = primary_snip.lower()
                        weak = len((reply or "").strip()) < 80
                        # Hallucination guards
                        if primary_low and any(
                            k in primary_low
                            for k in (
                                "prime minister",
                                "politician",
                                "cricketer",
                                "cricket",
                                "president",
                                "scientist",
                            )
                        ):
                            if "actor" in low_reply and not any(
                                k in low_reply
                                for k in ("prime minister", "politician", "cricket", "cricketer")
                            ):
                                weak = True
                        # If research extract is long and model barely overlaps key tokens, trust web
                        key_tokens = [
                            w
                            for w in primary_low.replace(",", " ").split()
                            if len(w) > 5
                        ][:8]
                        if key_tokens:
                            hits = sum(1 for w in key_tokens if w in low_reply)
                            if hits <= 1 and len(primary_snip) > 100:
                                weak = True
                        if weak:
                            reply = grounded
                            model_used = f"{model_used}+web-grounded"
                        elif sources and "Source:" not in reply and "http" not in reply:
                            cites = "\n\nSources:\n" + "\n".join(
                                f"- {s.get('title') or 'link'}: {s.get('url')}"
                                for s in sources[:4]
                                if s.get("url")
                            )
                            reply = (reply or "").rstrip() + cites
                            model_used = f"{model_used}+web"
            except Exception as error:  # noqa: BLE001
                # Fallback: web-grounded answer if available, else expert pack for harnessy Qs
                try:
                    from sophyane.web_intel import grounded_answer_from_search, needs_web_research, web_search

                    if needs_web_research(message) or force_search:
                        search_meta = web_search(message, limit=6)
                        grounded = grounded_answer_from_search(message, search_meta)
                        if grounded:
                            reply = grounded
                            model_used = "web-grounded"
                            sources = [
                                {"title": h.get("title"), "url": h.get("url"), "source": h.get("source")}
                                for h in (search_meta.get("results") or [])
                            ]
                except Exception:  # noqa: BLE001
                    pass
                if not (reply or "").strip():
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
                        try:
                            from sophyane.web_intel import grounded_answer_from_search, web_search

                            sm = web_search(message, limit=6)
                            g = grounded_answer_from_search(message, sm)
                            if g:
                                reply = g
                                model_used = "web-grounded-fallback"
                                sources = [
                                    {
                                        "title": h.get("title"),
                                        "url": h.get("url"),
                                        "source": h.get("source"),
                                    }
                                    for h in (sm.get("results") or [])
                                ]
                            else:
                                reply = (
                                    "I could not reach a live language model just now "
                                    f"({error}). Open **Models** to add an API key "
                                    "(OpenAI / Claude / Gemini / Grok), keep **Web search** on for facts, "
                                    "or use **Local free** GGUF/Ollama."
                                )
                                model_used = "error-fallback"
                        except Exception:
                            reply = (
                                "I could not reach a live language model just now "
                                f"({error}). Open **Models** for API keys or enable **Web search**."
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
                    "sources": sources,
                    "web_search": bool(sources) or bool(search_meta.get("ok")),
                },
            )
            return True

        if path == "/api/v1/search" and method == "POST":
            key = _auth_key(handler)
            principal = self.store.resolve_key(key) if key else None
            if not principal:
                _json(handler, 401, {"ok": False, "error": "invalid API key"})
                return True
            body = _read_json(handler)
            query = str(body.get("query") or body.get("message") or "").strip()
            if not query:
                _json(handler, 400, {"ok": False, "error": "query required"})
                return True
            from sophyane.web_intel import web_search

            result = web_search(query, limit=int(body.get("limit") or 6))
            _json(handler, 200, {"ok": True, **result})
            return True

        if path == "/api/v1/agent" and method == "POST":
            # Agentic harness / CLI-style tool loop (same auth as chat)
            key = _auth_key(handler)
            principal = self.store.resolve_key(key) if key else None
            if not principal:
                _json(handler, 401, {"ok": False, "error": "invalid API key — sign in first"})
                return True
            body = _read_json(handler)
            message = str(body.get("message") or body.get("prompt") or body.get("command") or "").strip()
            if not message:
                _json(handler, 400, {"ok": False, "error": "message required"})
                return True
            steps: list[dict[str, Any]] = []
            reply = ""
            model_used = "agent-harness"
            try:
                from sophyane.agent_runtime import route_local_request, tools_help
                from sophyane.web_intel import format_search_context, grounded_answer_from_search, web_search

                # Slash / natural local tools first (high throughput, no LLM needed)
                routed = route_local_request(message)
                if routed.get("handled"):
                    if routed.get("direct"):
                        reply = str(routed["direct"])
                        steps.append({"step": "local_tool", "tool": routed.get("tool_name") or "slash", "ok": True})
                    elif routed.get("context"):
                        # Summarize tool context with LLM if available
                        tool_ctx = str(routed["context"])
                        steps.append(
                            {
                                "step": "local_tool",
                                "tool": routed.get("tool_name") or "tool",
                                "ok": True,
                                "preview": tool_ctx[:400],
                            }
                        )
                        try:
                            from sophyane.config import load_config
                            from sophyane.main import create_provider

                            provider = create_provider(load_config())
                            reply = provider.generate(
                                f"Tool output:\n{tool_ctx[:4000]}\n\nUser: {message}\nSummarize clearly.",
                                "You are Sophyane Agent Harness. Report tool results accurately.",
                            )
                            model_used = str(getattr(provider, "model", None) or "provider")
                        except Exception:  # noqa: BLE001
                            reply = tool_ctx
                    else:
                        reply = tools_help()
                else:
                    # Plan → research → answer (agent loop)
                    from sophyane.web_intel import needs_web_research

                    steps.append({"step": "plan", "ok": True, "plan": "research + answer + cite"})
                    search = web_search(message, limit=6)
                    steps.append(
                        {
                            "step": "web_search",
                            "ok": bool(search.get("ok")),
                            "count": search.get("count") or 0,
                        }
                    )
                    research = format_search_context(search)
                    grounded_fast = grounded_answer_from_search(message, search)
                    # Prefer web extract for factual Qs — avoid hanging on local GGUF
                    if grounded_fast and needs_web_research(message):
                        reply = grounded_fast
                        model_used = "web-grounded"
                        steps.append({"step": "generate", "ok": True, "model": model_used, "path": "web-first"})
                    else:
                        try:
                            from sophyane.config import load_config
                            from sophyane.main import create_provider
                            import concurrent.futures

                            provider = create_provider(load_config())
                            system = (
                                "You are Sophyane Agent Harness (CLI agent). "
                                "Plan briefly, use research facts, answer the user, cite sources. "
                                "Prefer tool/research facts over model memory."
                            )
                            prompt = (research + "\n\n" if research else "") + f"USER: {message}"
                            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                                fut = pool.submit(provider.generate, prompt, system)
                                reply = fut.result(timeout=20)
                            model_used = str(getattr(provider, "model", None) or "provider")
                            if search.get("ok") and len((reply or "").strip()) < 40:
                                reply = grounded_fast or reply
                                model_used = f"{model_used}+web-grounded"
                            steps.append({"step": "generate", "ok": True, "model": model_used})
                        except Exception as gen_err:  # noqa: BLE001
                            grounded = grounded_fast or grounded_answer_from_search(message, search)
                            if grounded:
                                reply = grounded
                                model_used = "web-grounded"
                                steps.append({"step": "generate", "ok": True, "fallback": "web-grounded"})
                            else:
                                reply = f"Agent could not complete generation: {gen_err}"
                                steps.append({"step": "generate", "ok": False, "error": str(gen_err)})
                    # Attach sources
                    sources = [
                        {"title": h.get("title"), "url": h.get("url")}
                        for h in (search.get("results") or [])
                        if h.get("url")
                    ]
                    if sources and "Sources:" not in (reply or ""):
                        reply = (reply or "").rstrip() + "\n\nSources:\n" + "\n".join(
                            f"- {s['title']}: {s['url']}" for s in sources[:5]
                        )
                    steps.append({"step": "verify", "ok": bool(reply), "sources": len(sources)})
            except Exception as error:  # noqa: BLE001
                reply = f"Agent harness error: {error}"
                steps.append({"step": "error", "ok": False, "error": str(error)})

            tokens = max(1, (len(message) + len(reply)) // 4)
            self.store.record_usage(principal["user_id"], tokens, key_id=principal["key_id"], endpoint="/api/v1/agent")
            _json(
                handler,
                200,
                {
                    "ok": True,
                    "reply": reply,
                    "steps": steps,
                    "model": model_used,
                    "mode": "agent-harness",
                    "user": principal.get("email"),
                    "version": __version__,
                    "usage": {"tokens_estimate": tokens},
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
