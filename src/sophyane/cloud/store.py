"""SQLite store for API users, keys, and usage metering."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any

DEFAULT_DB = Path.home() / ".local" / "state" / "sophyane" / "cloud" / "portal.db"


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
                  created_at REAL NOT NULL
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
                CREATE INDEX IF NOT EXISTS idx_usage_user ON usage(user_id, ts);
                """
            )

    @staticmethod
    def _hash_key(raw: str) -> str:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def create_user(self, email: str, name: str = "", plan: str = "free") -> dict[str, Any]:
        email = email.strip().lower()
        uid = secrets.token_hex(8)
        now = time.time()
        with self._conn() as conn:
            existing = conn.execute("SELECT id, email, name, plan, created_at FROM users WHERE email=?", (email,)).fetchone()
            if existing:
                return dict(existing)
            conn.execute(
                "INSERT INTO users(id, email, name, plan, created_at) VALUES (?,?,?,?,?)",
                (uid, email, name or email.split("@")[0], plan, now),
            )
        return {"id": uid, "email": email, "name": name, "plan": plan, "created_at": now}

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

    def resolve_key(self, raw_key: str) -> dict[str, Any] | None:
        if not raw_key or not raw_key.startswith("sph_"):
            return None
        h = self._hash_key(raw_key.strip())
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT k.id as key_id, k.user_id, k.revoked, u.email, u.plan, u.name
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
            keys = conn.execute("SELECT COUNT(*) c FROM api_keys WHERE revoked=0").fetchone()["c"]
            tokens = conn.execute("SELECT COALESCE(SUM(tokens),0) c FROM usage").fetchone()["c"]
        return {"users": users, "active_keys": keys, "tokens_served": tokens}
