"""Unified auth: signup/signin + OTP + Google/Facebook OAuth.
Existing verified users and OAuth users login WITHOUT OTP.
OTP required only for new email/password signup verification (or re-verify if forced).
"""
from __future__ import annotations
import hashlib, hmac, json, os, secrets, smtplib, ssl, time, uuid
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# In-memory store (per process). Optional JSON persistence under product data dir.
_USERS: dict[str, dict] = {}          # email_lower -> user
_SESSIONS: dict[str, dict] = {}       # token -> {email, exp}
_OTPS: dict[str, dict] = {}           # email_lower -> {code, exp, purpose}
_BY_PROVIDER: dict[str, str] = {}     # "google:123" -> email

def _now() -> float:
    return time.time()

def _iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def _uid(prefix: str = "usr") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

def _hash_pw(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return salt, digest

def _check_pw(password: str, salt: str, digest: str) -> bool:
    _, d = _hash_pw(password, salt)
    return hmac.compare_digest(d, digest)

def _load_env_file(p: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out

def load_auth_config() -> dict[str, str]:
    cfg: dict[str, str] = {}
    home = Path.home() / ".config" / "sophyane"
    for name in ("auth.env", "oauth.env", "messaging.env", "stripe.env"):
        cfg.update(_load_env_file(home / name))
    # SMTP from shmry email
    cfg.update(_load_env_file(Path.home() / ".shmry_email.env"))
    for k, v in os.environ.items():
        if k.startswith(("GOOGLE_", "FACEBOOK_", "OAUTH_", "SMTP_", "AUTH_")):
            cfg[k] = v
    return cfg

def _send_otp_email(to_email: str, code: str, product: str, cfg: dict) -> dict:
    """Send OTP email. Always returns demo_code unless AUTH_EXPOSE_OTP=false (for client testing)."""
    expose = cfg.get("AUTH_EXPOSE_OTP", "true").lower() != "false"
    host = cfg.get("SMTP_HOST")
    user = cfg.get("SMTP_USER")
    password = cfg.get("SMTP_PASS")
    port = int(cfg.get("SMTP_PORT") or 587)
    out = {"sent": False, "demo_code": code if expose else None}
    if not (host and user and password):
        out["note"] = "SMTP not configured; use demo_code"
        return out
    try:
        msg = MIMEText(f"Your {product} verification code is: {code}\nValid for 10 minutes.\n")
        msg["Subject"] = f"{product} login code {code}"
        msg["From"] = user
        msg["To"] = to_email
        ctx = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.starttls(context=ctx)
            s.login(user, password)
            s.sendmail(user, [to_email], msg.as_string())
        out["sent"] = True
        out["note"] = "OTP emailed" + ("; demo_code also returned for clients" if expose else "")
        return out
    except Exception as e:
        out["error"] = str(e)
        out["note"] = "email failed; use demo_code"
        out["demo_code"] = code  # always expose on failure
        return out

def _public_user(u: dict) -> dict:
    return {
        "id": u["id"],
        "email": u["email"],
        "name": u.get("name") or "",
        "verified": bool(u.get("verified")),
        "providers": list(u.get("providers") or []),
        "created_at": u.get("created_at"),
        "otp_required_on_login": False if u.get("verified") else True,
    }

def signup(email: str, password: str, name: str = "", product: str = "app") -> dict:
    email_l = (email or "").strip().lower()
    if not email_l or "@" not in email_l:
        return {"ok": False, "error": "invalid_email"}
    if not password or len(password) < 6:
        return {"ok": False, "error": "password_min_6"}
    if email_l in _USERS:
        return {"ok": False, "error": "email_already_registered", "hint": "Use /auth/login or social login"}
    salt, digest = _hash_pw(password)
    u = {
        "id": _uid("usr"),
        "email": email_l,
        "name": name or email_l.split("@")[0],
        "salt": salt,
        "password_hash": digest,
        "verified": False,
        "providers": ["password"],
        "created_at": _iso(),
    }
    _USERS[email_l] = u
    otp = _issue_otp(email_l, "signup")
    cfg = load_auth_config()
    mail = _send_otp_email(email_l, otp["code"], product, cfg)
    return {
        "ok": True,
        "user": _public_user(u),
        "otp_required": True,
        "otp": {"purpose": "signup", "expires_in_sec": 600, **{k: v for k, v in mail.items() if k != "code"}},
        "message": "Account created. Verify OTP to activate. After verification, future logins skip OTP.",
    }

def _issue_otp(email_l: str, purpose: str) -> dict:
    code = f"{secrets.randbelow(1_000_000):06d}"
    _OTPS[email_l] = {"code": code, "exp": _now() + 600, "purpose": purpose}
    return {"code": code, "exp": _OTPS[email_l]["exp"], "purpose": purpose}

def request_otp(email: str, purpose: str = "login", product: str = "app") -> dict:
    email_l = (email or "").strip().lower()
    if email_l not in _USERS and purpose != "signup":
        return {"ok": False, "error": "user_not_found"}
    otp = _issue_otp(email_l, purpose)
    mail = _send_otp_email(email_l, otp["code"], product, load_auth_config())
    return {"ok": True, "email": email_l, "purpose": purpose, "expires_in_sec": 600, **mail}

def verify_otp(email: str, code: str) -> dict:
    email_l = (email or "").strip().lower()
    rec = _OTPS.get(email_l)
    if not rec:
        return {"ok": False, "error": "otp_not_found"}
    if _now() > rec["exp"]:
        return {"ok": False, "error": "otp_expired"}
    if not hmac.compare_digest(str(code).strip(), rec["code"]):
        return {"ok": False, "error": "otp_invalid"}
    del _OTPS[email_l]
    u = _USERS.get(email_l)
    if not u:
        return {"ok": False, "error": "user_not_found"}
    u["verified"] = True
    token = _create_session(email_l)
    return {
        "ok": True,
        "verified": True,
        "token": token,
        "user": _public_user(u),
        "message": "Verified. Future password logins will not require OTP.",
    }

def _create_session(email_l: str, days: int = 30) -> str:
    token = secrets.token_urlsafe(32)
    _SESSIONS[token] = {"email": email_l, "exp": _now() + days * 86400, "created_at": _iso()}
    return token

def login(email: str, password: str, product: str = "app", force_otp: bool = False) -> dict:
    email_l = (email or "").strip().lower()
    u = _USERS.get(email_l)
    if not u or "password" not in (u.get("providers") or []):
        return {"ok": False, "error": "invalid_credentials"}
    if not _check_pw(password, u["salt"], u["password_hash"]):
        return {"ok": False, "error": "invalid_credentials"}
    # Existing verified users: NO OTP
    if u.get("verified") and not force_otp:
        token = _create_session(email_l)
        return {
            "ok": True,
            "otp_required": False,
            "token": token,
            "user": _public_user(u),
            "message": "Welcome back — OTP skipped for verified/existing user.",
        }
    # Unverified: require OTP
    otp = _issue_otp(email_l, "login")
    mail = _send_otp_email(email_l, otp["code"], product, load_auth_config())
    return {
        "ok": True,
        "otp_required": True,
        "user": _public_user(u),
        "otp": {"purpose": "login", "expires_in_sec": 600, **mail},
        "message": "OTP required to complete first-time verification.",
    }

def _verify_google_token(id_token: str, cfg: dict) -> dict | None:
    try:
        req = Request(f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}")
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        email = (data.get("email") or "").lower()
        if not email:
            return None
        # optional audience check
        aud = cfg.get("GOOGLE_CLIENT_ID")
        if aud and data.get("aud") and data.get("aud") != aud:
            return None
        return {"email": email, "name": data.get("name") or email.split("@")[0], "provider_user_id": data.get("sub") or email}
    except Exception:
        return None

def _verify_facebook_token(access_token: str, cfg: dict) -> dict | None:
    try:
        req = Request(f"https://graph.facebook.com/me?fields=id,name,email&access_token={access_token}")
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        email = (data.get("email") or f"fb_{data.get('id')}@facebook.local").lower()
        return {"email": email, "name": data.get("name") or "Facebook User", "provider_user_id": str(data.get("id") or email)}
    except Exception:
        return None

def oauth_login(provider: str, token: str | None = None, profile: dict | None = None, product: str = "app") -> dict:
    """Login/signup via Google or Facebook. Always skips OTP (trusted identity provider).
    - Production: pass Google id_token or Facebook access_token
    - Demo: pass profile={email,name,provider_user_id} with AUTH_DEMO_OAUTH=1 or missing real token validation
    """
    provider = (provider or "").lower().strip()
    if provider not in ("google", "facebook", "gmail"):
        return {"ok": False, "error": "unsupported_provider", "allowed": ["google", "facebook"]}
    if provider == "gmail":
        provider = "google"
    cfg = load_auth_config()
    info = None
    if token:
        if provider == "google":
            info = _verify_google_token(token, cfg)
        else:
            info = _verify_facebook_token(token, cfg)
    if not info and profile and (cfg.get("AUTH_DEMO_OAUTH", "true").lower() != "false"):
        # Demo / client-side already-authenticated profile (for local apps)
        email = (profile.get("email") or "").strip().lower()
        if email and "@" in email:
            info = {
                "email": email,
                "name": profile.get("name") or email.split("@")[0],
                "provider_user_id": str(profile.get("provider_user_id") or profile.get("id") or email),
            }
    if not info:
        return {
            "ok": False,
            "error": "oauth_validation_failed",
            "hint": "Provide valid Google id_token / Facebook access_token, or demo profile when AUTH_DEMO_OAUTH=true",
        }
    email_l = info["email"]
    key = f"{provider}:{info['provider_user_id']}"
    u = _USERS.get(email_l)
    if not u:
        # auto-provision — verified, no OTP
        u = {
            "id": _uid("usr"),
            "email": email_l,
            "name": info.get("name") or email_l.split("@")[0],
            "salt": "",
            "password_hash": "",
            "verified": True,
            "providers": [provider],
            "created_at": _iso(),
        }
        _USERS[email_l] = u
    else:
        u["verified"] = True
        provs = list(u.get("providers") or [])
        if provider not in provs:
            provs.append(provider)
            u["providers"] = provs
        if info.get("name") and not u.get("name"):
            u["name"] = info["name"]
    _BY_PROVIDER[key] = email_l
    token_sess = _create_session(email_l)
    return {
        "ok": True,
        "otp_required": False,
        "provider": provider,
        "token": token_sess,
        "user": _public_user(u),
        "message": f"Logged in with {provider}. OTP not required for social / existing verified users.",
    }

def logout(token: str) -> dict:
    if token in _SESSIONS:
        del _SESSIONS[token]
    return {"ok": True}

def me(token: str | None) -> dict:
    if not token:
        return {"ok": False, "error": "missing_token"}
    sess = _SESSIONS.get(token)
    if not sess or _now() > sess["exp"]:
        return {"ok": False, "error": "invalid_or_expired_token"}
    u = _USERS.get(sess["email"])
    if not u:
        return {"ok": False, "error": "user_missing"}
    return {"ok": True, "user": _public_user(u)}

def require_auth(headers: dict) -> dict | None:
    """Return user public dict or None. Accepts Authorization: Bearer <token> or X-Auth-Token."""
    auth = headers.get("Authorization") or headers.get("authorization") or ""
    token = headers.get("X-Auth-Token") or headers.get("x-auth-token") or ""
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
    res = me(token)
    return res.get("user") if res.get("ok") else None

def auth_capabilities() -> dict:
    cfg = load_auth_config()
    return {
        "signup": True,
        "login_password": True,
        "otp": True,
        "otp_skip_for_verified_users": True,
        "oauth": {
            "google": True,
            "facebook": True,
            "google_client_id_configured": bool(cfg.get("GOOGLE_CLIENT_ID")),
            "facebook_app_id_configured": bool(cfg.get("FACEBOOK_APP_ID")),
            "demo_oauth_profile": cfg.get("AUTH_DEMO_OAUTH", "true").lower() != "false",
        },
        "routes": [
            "POST /auth/signup",
            "POST /auth/login",
            "POST /auth/otp/request",
            "POST /auth/otp/verify",
            "POST /auth/oauth/google",
            "POST /auth/oauth/facebook",
            "GET  /auth/me",
            "POST /auth/logout",
            "GET  /auth/capabilities",
        ],
    }

def handle_auth_request(method: str, path: str, body: dict, headers: dict | None = None, product: str = "app") -> tuple[int, dict]:
    """Router helper for product servers. path like /auth/login"""
    headers = headers or {}
    p = path.rstrip("/") or "/"
    if method == "GET" and p in ("/auth", "/auth/capabilities"):
        return 200, {"ok": True, "product": product, **auth_capabilities()}
    if method == "GET" and p == "/auth/me":
        return (200 if me((headers.get("Authorization") or "").replace("Bearer ", "").strip() or headers.get("X-Auth-Token") or "").get("ok") else 401), me(
            (headers.get("Authorization") or "").split(" ")[-1] if headers.get("Authorization") else headers.get("X-Auth-Token")
        )
    if method == "POST" and p == "/auth/signup":
        r = signup(body.get("email") or "", body.get("password") or "", body.get("name") or "", product)
        return (201 if r.get("ok") else 400), r
    if method == "POST" and p == "/auth/login":
        r = login(body.get("email") or "", body.get("password") or "", product, force_otp=bool(body.get("force_otp")))
        return (200 if r.get("ok") else 401), r
    if method == "POST" and p in ("/auth/otp/request", "/auth/otp"):
        r = request_otp(body.get("email") or "", body.get("purpose") or "login", product)
        return (200 if r.get("ok") else 400), r
    if method == "POST" and p == "/auth/otp/verify":
        r = verify_otp(body.get("email") or "", body.get("code") or body.get("otp") or "")
        return (200 if r.get("ok") else 400), r
    if method == "POST" and p in ("/auth/oauth/google", "/auth/google", "/auth/gmail"):
        r = oauth_login("google", token=body.get("id_token") or body.get("token"), profile=body.get("profile"), product=product)
        return (200 if r.get("ok") else 401), r
    if method == "POST" and p in ("/auth/oauth/facebook", "/auth/facebook"):
        r = oauth_login("facebook", token=body.get("access_token") or body.get("token"), profile=body.get("profile"), product=product)
        return (200 if r.get("ok") else 401), r
    if method == "POST" and p == "/auth/logout":
        tok = body.get("token") or ""
        if not tok and headers.get("Authorization"):
            tok = headers["Authorization"].split(" ")[-1]
        return 200, logout(tok)
    return 404, {"ok": False, "error": "auth_route_not_found", "path": p}
