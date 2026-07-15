"""SQLite store for API users, keys, OTP auth, and usage metering."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any

DEFAULT_DB = Path.home() / ".local" / "state" / "sophyane" / "cloud" / "portal.db"
OTP_TTL_SEC = 600  # 10 minutes
OTP_COOLDOWN_SEC = 45  # min between resends


class PortalStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_DB
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                  id TEXT PRIMARY KEY,
                  email TEXT UNIQUE NOT NULL,
                  name TEXT,
                  plan TEXT NOT NULL DEFAULT 'free',
                  created_at REAL NOT NULL,
                  email_verified INTEGER NOT NULL DEFAULT 0,
                  last_login_at REAL
                );
                CREATE TABLE IF NOT EXISTS api_keys (
                  id TEXT PRIMARY KEY,
                  user_id TEXT NOT NULL,
                  key_hash TEXT NOT NULL,
                  key_prefix TEXT NOT NULL,
                  label TEXT,
                  created_at REAL NOT NULL,
                  revoked INTEGER NOT NULL DEFAULT 0,
                  FOREIGN KEY(user_id) REFERENCES users(id)
                );
                CREATE TABLE IF NOT EXISTS usage (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id TEXT NOT NULL,
                  key_id TEXT,
                  tokens INTEGER NOT NULL,
                  endpoint TEXT,
                  ts REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS email_otps (
                  id TEXT PRIMARY KEY,
                  email TEXT NOT NULL,
                  otp_hash TEXT NOT NULL,
                  purpose TEXT NOT NULL,
                  name TEXT,
                  plan TEXT,
                  created_at REAL NOT NULL,
                  expires_at REAL NOT NULL,
                  used INTEGER NOT NULL DEFAULT 0,
                  attempts INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_usage_user ON usage(user_id, ts);
                CREATE INDEX IF NOT EXISTS idx_otp_email ON email_otps(email, purpose, created_at);
                """
            )
            # migrate older DBs missing columns
            cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
            if "email_verified" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0")
            if "last_login_at" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN last_login_at REAL")

    @staticmethod
    def _hash_key(raw: str) -> str:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _hash_otp(email: str, otp: str) -> str:
        return hashlib.sha256(f"{email.strip().lower()}:{otp.strip()}".encode("utf-8")).hexdigest()

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        email = email.strip().lower()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, email, name, plan, created_at, email_verified, last_login_at FROM users WHERE email=?",
                (email,),
            ).fetchone()
        return dict(row) if row else None

    def create_user(
        self,
        email: str,
        name: str = "",
        plan: str = "free",
        *,
        verified: bool = False,
    ) -> dict[str, Any]:
        email = email.strip().lower()
        uid = secrets.token_hex(8)
        now = time.time()
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT id, email, name, plan, created_at, email_verified, last_login_at FROM users WHERE email=?",
                (email,),
            ).fetchone()
            if existing:
                return dict(existing)
            conn.execute(
                "INSERT INTO users(id, email, name, plan, created_at, email_verified) VALUES (?,?,?,?,?,?)",
                (uid, email, name or email.split("@")[0], plan, now, 1 if verified else 0),
            )
        return {
            "id": uid,
            "email": email,
            "name": name or email.split("@")[0],
            "plan": plan,
            "created_at": now,
            "email_verified": 1 if verified else 0,
            "last_login_at": None,
        }

    def mark_verified_login(self, user_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET email_verified=1, last_login_at=? WHERE id=?",
                (time.time(), user_id),
            )

    def update_plan(self, user_id: str, plan: str) -> dict[str, Any]:
        plan = (plan or "free").strip().lower()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, email, name, plan, email_verified FROM users WHERE id=?",
                (user_id,),
            ).fetchone()
            if not row:
                return {"ok": False, "error": "user not found"}
            conn.execute("UPDATE users SET plan=? WHERE id=?", (plan, user_id))
            return {
                "ok": True,
                "user": {
                    "id": row["id"],
                    "email": row["email"],
                    "name": row["name"],
                    "plan": plan,
                    "email_verified": bool(row["email_verified"]),
                },
                "previous_plan": row["plan"],
            }

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, email, name, plan, created_at, email_verified, last_login_at FROM users WHERE id=?",
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def issue_key(self, user_id: str, label: str = "default") -> dict[str, Any]:
        raw = "sph_" + secrets.token_urlsafe(32)
        kid = secrets.token_hex(8)
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO api_keys(id, user_id, key_hash, key_prefix, label, created_at) VALUES (?,?,?,?,?,?)",
                (kid, user_id, self._hash_key(raw), raw[:12], label, now),
            )
        return {
            "ok": True,
            "key_id": kid,
            "api_key": raw,
            "prefix": raw[:12],
            "label": label,
            "note": "Store this key now; it will not be shown again in full.",
        }

    def latest_active_key_prefix(self, user_id: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT key_prefix FROM api_keys WHERE user_id=? AND revoked=0 ORDER BY created_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        return row["key_prefix"] if row else None

    def resolve_key(self, raw_key: str) -> dict[str, Any] | None:
        if not raw_key or not raw_key.startswith("sph_"):
            return None
        h = self._hash_key(raw_key.strip())
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT k.id as key_id, k.user_id, k.revoked, u.email, u.plan, u.name, u.email_verified
                FROM api_keys k JOIN users u ON u.id = k.user_id
                WHERE k.key_hash=?
                """,
                (h,),
            ).fetchone()
        if not row or row["revoked"]:
            return None
        return dict(row)

    def record_usage(self, user_id: str, tokens: int, *, key_id: str = "", endpoint: str = "") -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO usage(user_id, key_id, tokens, endpoint, ts) VALUES (?,?,?,?,?)",
                (user_id, key_id, int(tokens), endpoint, time.time()),
            )

    def usage_summary(self, user_id: str, *, since: float | None = None) -> dict[str, Any]:
        since = since or (time.time() - 30 * 86400)
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(tokens),0) as tokens, COUNT(*) as calls FROM usage WHERE user_id=? AND ts>=?",
                (user_id, since),
            ).fetchone()
        return {"tokens": int(row["tokens"]), "calls": int(row["calls"]), "since": since}

    def stats(self) -> dict[str, Any]:
        with self._conn() as conn:
            users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
            verified = conn.execute("SELECT COUNT(*) c FROM users WHERE email_verified=1").fetchone()["c"]
            keys = conn.execute("SELECT COUNT(*) c FROM api_keys WHERE revoked=0").fetchone()["c"]
            tokens = conn.execute("SELECT COALESCE(SUM(tokens),0) c FROM usage").fetchone()["c"]
        return {"users": users, "verified_users": verified, "active_keys": keys, "tokens_served": tokens}

    # --- OTP ---

    def create_otp(
        self,
        email: str,
        purpose: str,
        *,
        name: str = "",
        plan: str = "free",
    ) -> dict[str, Any]:
        """Create a new OTP. purpose: signup | login."""
        email = email.strip().lower()
        purpose = purpose.strip().lower()
        if purpose not in {"signup", "login"}:
            return {"ok": False, "error": "purpose must be signup or login"}
        now = time.time()
        with self._conn() as conn:
            recent = conn.execute(
                """
                SELECT created_at FROM email_otps
                WHERE email=? AND purpose=? AND used=0
                ORDER BY created_at DESC LIMIT 1
                """,
                (email, purpose),
            ).fetchone()
            if recent and (now - float(recent["created_at"])) < OTP_COOLDOWN_SEC:
                wait = int(OTP_COOLDOWN_SEC - (now - float(recent["created_at"])))
                return {"ok": False, "error": f"wait {wait}s before requesting another code"}

            # For signup: only once — if already verified user exists, use login
            user = conn.execute("SELECT id, email_verified FROM users WHERE email=?", (email,)).fetchone()
            if purpose == "signup" and user and int(user["email_verified"] or 0) == 1:
                return {
                    "ok": False,
                    "error": "email already registered — use login",
                    "code": "already_registered",
                }
            if purpose == "login" and not user:
                return {"ok": False, "error": "no account for this email — use signup", "code": "not_registered"}

            otp = f"{secrets.randbelow(1_000_000):06d}"
            oid = secrets.token_hex(8)
            conn.execute(
                """
                INSERT INTO email_otps(id, email, otp_hash, purpose, name, plan, created_at, expires_at, used, attempts)
                VALUES (?,?,?,?,?,?,?,?,0,0)
                """,
                (
                    oid,
                    email,
                    self._hash_otp(email, otp),
                    purpose,
                    name,
                    plan,
                    now,
                    now + OTP_TTL_SEC,
                ),
            )
        return {
            "ok": True,
            "otp_id": oid,
            "otp": otp,  # caller sends via email; not returned to HTTP client
            "email": email,
            "purpose": purpose,
            "expires_in": OTP_TTL_SEC,
        }

    def verify_otp(self, email: str, otp: str, purpose: str) -> dict[str, Any]:
        email = email.strip().lower()
        otp = (otp or "").strip().replace(" ", "")
        purpose = purpose.strip().lower()
        now = time.time()
        h = self._hash_otp(email, otp)
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM email_otps
                WHERE email=? AND purpose=? AND used=0
                ORDER BY created_at DESC LIMIT 1
                """,
                (email, purpose),
            ).fetchone()
            if not row:
                return {"ok": False, "error": "no active code — request a new OTP"}
            conn.execute("UPDATE email_otps SET attempts=attempts+1 WHERE id=?", (row["id"],))
            if float(row["expires_at"]) < now:
                return {"ok": False, "error": "code expired — request a new OTP"}
            if int(row["attempts"] or 0) >= 8:
                return {"ok": False, "error": "too many attempts — request a new OTP"}
            if row["otp_hash"] != h:
                return {"ok": False, "error": "invalid code"}
            conn.execute("UPDATE email_otps SET used=1 WHERE id=?", (row["id"],))
            meta = {
                "name": row["name"] or "",
                "plan": row["plan"] or "free",
                "purpose": purpose,
            }
        return {"ok": True, "email": email, **meta}
