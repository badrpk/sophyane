from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DB = ROOT / "email_service.sqlite3"
SESSIONS: dict[str, int] = {}


def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db():
    ROOT.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,salt TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS subscriptions(id INTEGER PRIMARY KEY,user_id INTEGER UNIQUE NOT NULL,plan TEXT NOT NULL DEFAULT 'free',status TEXT NOT NULL DEFAULT 'active',provider_ref TEXT,FOREIGN KEY(user_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,sender_id INTEGER NOT NULL,recipient TEXT NOT NULL,subject TEXT NOT NULL,body TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'queued',created_at TEXT DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(sender_id) REFERENCES users(id));
        """)


def password_hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 210_000).hex()


class API(BaseHTTPRequestHandler):
    server_version = "Postly/1"

    def send_json(self, status, payload):
        raw = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise ValueError("request too large")
        data = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(data, dict):
            raise ValueError("JSON object required")
        return data

    def user_id(self):
        auth = self.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        return SESSIONS.get(token)

    def do_POST(self):
        try:
            data = self.body()
            path = urlparse(self.path).path
            if path == "/api/register":
                email = str(data.get("email", "")).strip().casefold()
                password = str(data.get("password", ""))
                if "@" not in email or len(password) < 10:
                    return self.send_json(400, {"error": "valid email and 10-character password required"})
                salt = secrets.token_bytes(16)
                with connect() as db:
                    cur = db.execute("INSERT INTO users(email,password_hash,salt) VALUES(?,?,?)", (email, password_hash(password, salt), salt.hex()))
                    db.execute("INSERT INTO subscriptions(user_id) VALUES(?)", (cur.lastrowid,))
                return self.send_json(201, {"ok": True})
            if path == "/api/login":
                email = str(data.get("email", "")).strip().casefold()
                with connect() as db:
                    row = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
                valid = row and hmac.compare_digest(row["password_hash"], password_hash(str(data.get("password", "")), bytes.fromhex(row["salt"])))
                if not valid:
                    return self.send_json(401, {"error": "invalid credentials"})
                token = secrets.token_urlsafe(32)
                SESSIONS[token] = row["id"]
                return self.send_json(200, {"token": token})
            uid = self.user_id()
            if not uid:
                return self.send_json(401, {"error": "authentication required"})
            if path == "/api/messages":
                recipient = str(data.get("recipient", "")).strip()
                subject = str(data.get("subject", "")).strip()[:200]
                body = str(data.get("body", "")).strip()[:100_000]
                if "@" not in recipient or not subject or not body:
                    return self.send_json(400, {"error": "recipient, subject and body required"})
                with connect() as db:
                    cur = db.execute("INSERT INTO messages(sender_id,recipient,subject,body) VALUES(?,?,?,?)", (uid, recipient, subject, body))
                return self.send_json(202, {"id": cur.lastrowid, "status": "queued"})
            if path == "/api/subscription":
                plan = str(data.get("plan", ""))
                if plan not in {"free", "pro", "business"}:
                    return self.send_json(400, {"error": "unknown plan"})
                with connect() as db:
                    db.execute("UPDATE subscriptions SET plan=?,status='pending_payment' WHERE user_id=?", (plan, uid))
                return self.send_json(200, {"plan": plan, "status": "pending_payment", "note": "connect a verified payment provider before activation"})
            return self.send_json(404, {"error": "not found"})
        except sqlite3.IntegrityError:
            self.send_json(409, {"error": "account already exists"})
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            return self.send_json(200, {"ok": True})
        uid = self.user_id()
        if path == "/api/dashboard" and uid:
            with connect() as db:
                sub = db.execute("SELECT plan,status FROM subscriptions WHERE user_id=?", (uid,)).fetchone()
                rows = db.execute("SELECT id,recipient,subject,status,created_at FROM messages WHERE sender_id=? ORDER BY id DESC LIMIT 50", (uid,)).fetchall()
            return self.send_json(200, {"subscription": dict(sub), "messages": [dict(row) for row in rows]})
        self.send_json(401 if path == "/api/dashboard" else 404, {"error": "authentication required" if path == "/api/dashboard" else "not found"})


if __name__ == "__main__":
    init_db()
    ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("PORT", "8080"))), API).serve_forever()
