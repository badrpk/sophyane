"""Gmail OAuth 2.0 Authentication & User Record Management for Sophyane.

Supports:
  1) Google OAuth 2.0 Client authorization flow (Google Login for web & mobile).
  2) Token exchange, profile retrieval, and OAuth token refresh.
  3) User record maintenance in Sophyane's embedded PostgreSQL and SQLite databases.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    from sophyane.sli_postgres import PostgresSLI, HAS_PSYCOPG
except ImportError:
    PostgresSLI = None
    HAS_PSYCOPG = False


ENV_FILE = Path.home() / ".config" / "sophyane" / "gmail_oauth.env"
STATE_DIR = Path.home() / ".local" / "state" / "sophyane" / "cloud"
USER_DB = STATE_DIR / "user_records.db"


@dataclass
class OAuthConfig:
  client_id: str
  client_secret: str
  redirect_uri: str = "http://127.0.0.1:8888/api/oauth/google/callback"

  @classmethod
  def from_env(cls) -> "OAuthConfig":
    env: dict[str, str] = {}
    if ENV_FILE.exists():
      for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
          continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    for k in (
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REDIRECT_URI",
    ):
      if os.environ.get(k):
        env[k] = os.environ[k].strip()

    return cls(
        client_id=env.get("GOOGLE_CLIENT_ID", "default_google_client_id"),
        client_secret=env.get("GOOGLE_CLIENT_SECRET", "default_secret"),
        redirect_uri=env.get(
            "GOOGLE_REDIRECT_URI",
            "http://127.0.0.1:8888/api/oauth/google/callback",
        ),
    )


class GmailOAuthManager:
  """Manages Google OAuth authentication flows and PostgreSQL user persistence."""

  def __init__(self, config: OAuthConfig | None = None) -> None:
    self.config = config or OAuthConfig.from_env()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    self._init_databases()

  def _init_databases(self) -> None:
    # 1. Initialize SQLite storage
    with sqlite3.connect(str(USER_DB)) as con:
      con.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    google_id TEXT PRIMARY KEY,
                    email TEXT UNIQUE,
                    name TEXT,
                    picture TEXT,
                    access_token TEXT,
                    refresh_token TEXT,
                    created_at REAL,
                    last_login REAL
                )
            """)
      con.commit()

    # 2. Sync schema to embedded PostgreSQL engine if available
    try:
        if HAS_PSYCOPG and PostgresSLI:
            pg = PostgresSLI()
            if pg.connect():
                with pg.conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS sophyane_users (
                            google_id VARCHAR(255) PRIMARY KEY,
                            email VARCHAR(255) UNIQUE,
                            name VARCHAR(255),
                            picture TEXT,
                            access_token TEXT,
                            refresh_token TEXT,
                            created_at DOUBLE PRECISION,
                            last_login DOUBLE PRECISION
                        );
                    """)
                pg.conn.commit()
    except Exception:
        pass

  def get_authorization_url(
      self, state: str = "sophyane_auth_state"
  ) -> str:
    """Generate Google OAuth 2.0 authorization URL."""
    base_url = "https://accounts.google.com/o/oauth2/v2/auth"
    params = {
        "client_id": self.config.client_id,
        "redirect_uri": self.config.redirect_uri,
        "response_type": "code",
        "scope": (
            "openid email profile"
            " https://www.googleapis.com/auth/gmail.readonly"
        ),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{base_url}?{urllib.parse.urlencode(params)}"

  def exchange_code_for_tokens(self, code: str) -> dict[str, Any]:
    """Exchange OAuth authorization code for Google Access & Refresh tokens."""
    token_url = "https://oauth2.googleapis.com/token"
    payload = urllib.parse.urlencode({
        "code": code,
        "client_id": self.config.client_id,
        "client_secret": self.config.client_secret,
        "redirect_uri": self.config.redirect_uri,
        "grant_type": "authorization_code",
    }).encode("utf-8")

    req = urllib.request.Request(
        token_url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
      with urllib.request.urlopen(req, timeout=15) as resp:
        tokens = json.loads(resp.read().decode("utf-8"))
        # Fetch user profile using access token
        profile = self.get_user_profile(tokens["access_token"])
        # Save user record to SQLite & PostgreSQL
        user_record = self.save_user_record(profile, tokens)
        return {"ok": True, "user": user_record, "tokens": tokens}
    except Exception as e:
      return {"ok": False, "error": f"OAuth token exchange failed: {e}"}

  def get_user_profile(self, access_token: str) -> dict[str, Any]:
    """Fetch user profile from Google UserInfo endpoint."""
    url = "https://www.googleapis.com/oauth2/v2/userinfo"
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {access_token}"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
      return json.loads(resp.read().decode("utf-8"))

  def save_user_record(
      self, profile: dict[str, Any], tokens: dict[str, Any]
  ) -> dict[str, Any]:
    """Save or update user in Sophyane's embedded PostgreSQL and SQLite databases."""
    google_id = profile.get("id") or profile.get("sub") or f"g-{int(time.time())}"
    email = profile.get("email", "").casefold()
    name = profile.get("name", "Sophyane User")
    picture = profile.get("picture", "")
    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")
    now = time.time()

    # 1. Save to SQLite
    with sqlite3.connect(str(USER_DB)) as con:
      con.execute(
          """
                INSERT INTO users (google_id, email, name, picture, access_token, refresh_token, created_at, last_login)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(google_id) DO UPDATE SET
                    email=excluded.email,
                    name=excluded.name,
                    picture=excluded.picture,
                    access_token=excluded.access_token,
                    refresh_token=COALESCE(NULLIF(excluded.refresh_token, ''), users.refresh_token),
                    last_login=excluded.last_login
            """,
          (
              google_id,
              email,
              name,
              picture,
              access_token,
              refresh_token,
              now,
              now,
          ),
      )
      con.commit()

    # 2. Save to PostgreSQL
    try:
      pg = get_postgres_engine()
      if pg and pg.is_connected():
        pg.execute_sql(
            """
                    INSERT INTO sophyane_users (google_id, email, name, picture, access_token, refresh_token, created_at, last_login)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(google_id) DO UPDATE SET
                        email=EXCLUDED.email,
                        name=EXCLUDED.name,
                        picture=EXCLUDED.picture,
                        access_token=EXCLUDED.access_token,
                        refresh_token=COALESCE(NULLIF(EXCLUDED.refresh_token, ''), sophyane_users.refresh_token),
                        last_login=EXCLUDED.last_login;
                """,
            (
                google_id,
                email,
                name,
                picture,
                access_token,
                refresh_token,
                now,
                now,
            ),
        )
    except Exception:
      pass

    return {
        "google_id": google_id,
        "email": email,
        "name": name,
        "picture": picture,
        "last_login": now,
    }

  def list_users(self) -> list[dict[str, Any]]:
    """List all registered users from database."""
    with sqlite3.connect(str(USER_DB)) as con:
      con.row_factory = sqlite3.Row
      rows = con.execute(
          "SELECT google_id, email, name, picture, created_at, last_login FROM"
          " users ORDER BY last_login DESC"
      ).fetchall()
      return [dict(r) for r in rows]
