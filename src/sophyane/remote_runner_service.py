"""Authenticated, durable HTTPS runner service for fixed deployment recipes."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from sophyane.remote_execution import (
    AuthenticationError, ReplayGuard, RequestAuthenticator, extract_project_archive,
    sha256, source_tree_sha256, validate_job_manifest,
)

MAX_BODY = 180 * 1024 * 1024
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"}


class RunnerService:
    """Owns job state, isolated workspaces, executor dispatch and evidence signing."""

    def __init__(
        self, root: str | Path, runner_id: str, secret: bytes,
        executors: dict[str, Callable[..., dict[str, Any]]], *,
        workers: int = 2, clock: Callable[[], float] = time.time,
        environment_identity: dict[str, Any] | None = None,
    ) -> None:
        if not runner_id or len(runner_id) > 128:
            raise ValueError("runner identity is required")
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.runner_id, self.clock = runner_id, clock
        self.environment_identity = dict(environment_identity or {
            "runner_id": runner_id, "execution_class": "unconfigured", "real_execution": False,
        })
        if self.environment_identity.get("runner_id") != runner_id:
            raise ValueError("environment identity runner_id must match service runner_id")
        self.auth = RequestAuthenticator(secret, clock=clock)
        self.replay = ReplayGuard(self.root / "runner.sqlite", clock=clock)
        self.executors = dict(executors)
        self.executor = ThreadPoolExecutor(max_workers=max(1, min(workers, 8)))
        self._locks: dict[str, threading.Event] = {}
        self._futures: dict[str, Any] = {}
        self._lock = threading.RLock()
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, manifest TEXT NOT NULL,
                state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                result TEXT, artifact BLOB, error TEXT, request BLOB)""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
            if "request" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN request BLOB")
            # A process restart cannot safely resume a partially executed compose or VM action.
            db.execute("UPDATE jobs SET state='INTERRUPTED', error='runner restarted during execution', updated=? WHERE state='RUNNING'", (clock(),))
            db.execute("UPDATE jobs SET state='QUEUED', updated=? WHERE state='QUEUED'", (clock(),))
            queued = db.execute("SELECT job_id,manifest,request FROM jobs WHERE state='QUEUED'").fetchall()
        for row in queued:
            if row["request"]:
                request = json.loads(bytes(row["request"]))
                archive = base64.b64decode(request["archive_b64"], validate=True)
                self._schedule(row["job_id"], json.loads(row["manifest"]), archive)

    def _connect(self):
        db = sqlite3.connect(self.root / "runner.sqlite", timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=15000")
        return db

    def close(self) -> None:
        with self._lock:
            for event in self._locks.values():
                event.set()
        self.executor.shutdown(wait=True, cancel_futures=True)

    def submit(self, body: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(body, dict) or set(body) != {"manifest", "archive_b64"}:
            raise ValueError("submit body must contain manifest and archive_b64")
        manifest = validate_job_manifest(body["manifest"])
        if manifest["kind"] not in self.executors:
            raise ValueError("runner does not support requested job kind")
        encoded = body["archive_b64"]
        if not isinstance(encoded, str) or len(encoded) > ((MAX_BODY * 4 // 3) + 8):
            raise ValueError("invalid or oversized archive")
        try:
            archive = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as error:
            raise ValueError("invalid base64 archive") from error
        if sha256(archive) != manifest["archive_sha256"]:
            raise ValueError("archive hash does not match manifest")
        request_hash = sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())
        job_id = manifest["job_id"]
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row:
                if row["request_hash"] != request_hash:
                    raise ValueError("job ID already exists with different request content")
                return self._public_row(row)
            now = self.clock()
            db.execute("INSERT INTO jobs(job_id,request_hash,manifest,state,created,updated,request) VALUES(?,?,?,?,?,?,?)",
                       (job_id, request_hash, json.dumps(manifest, sort_keys=True), "QUEUED", now, now,
                        json.dumps(body, sort_keys=True).encode()))
        self._schedule(job_id, manifest, archive)
        return self.get(job_id)

    def _schedule(self, job_id: str, manifest: dict[str, Any], archive: bytes) -> None:
        cancel = threading.Event()
        with self._lock:
            self._locks[job_id] = cancel
            self._futures[job_id] = self.executor.submit(self._run, job_id, manifest, archive, cancel)

    @staticmethod
    def _public_row(row: sqlite3.Row) -> dict[str, Any]:
        result = {"job_id": row["job_id"], "state": row["state"], "created_at": row["created"], "updated_at": row["updated"]}
        if row["error"]:
            result["error"] = row["error"]
        if row["result"]:
            result["result"] = json.loads(row["result"])
        return result

    def _run(self, job_id: str, manifest: dict[str, Any], archive: bytes, cancel: threading.Event) -> None:
        now = self.clock()
        with self._connect() as db:
            cursor = db.execute("UPDATE jobs SET state='RUNNING',updated=? WHERE job_id=? AND state='QUEUED'", (now, job_id))
            if not cursor.rowcount:
                return
            if cancel.is_set():
                db.execute("UPDATE jobs SET state='CANCELLED',updated=? WHERE job_id=?", (self.clock(), job_id))
                return
        job_root = Path(tempfile.mkdtemp(prefix=f"{job_id}-", dir=self.root))
        os.chmod(job_root, 0o700)
        started = self.clock()
        commands: list[dict[str, Any]] = []
        artifacts: dict[str, bytes] = {}
        status = "FAILED"
        error = ""
        try:
            source = job_root / "source"
            extract_project_archive(archive, source)
            if source_tree_sha256(source) != manifest["source_sha256"]:
                raise ValueError("extracted source does not match manifest digest")
            outcome = self.executors[manifest["kind"]](source, manifest, cancel)
            if not isinstance(outcome, dict):
                raise TypeError("executor must return an object")
            commands = list(outcome.get("commands", []))
            artifacts = dict(outcome.get("artifacts", {}))
            passed = outcome.get("passed") is True and not cancel.is_set()
            status = "COMPLETED" if passed else ("CANCELLED" if cancel.is_set() else "FAILED")
            error = str(outcome.get("error", ""))
        except BaseException as exc:
            status = "CANCELLED" if cancel.is_set() else "FAILED"
            error = f"{type(exc).__name__}: {exc}"[:1000]
        finally:
            ended = self.clock()
            finished_iso = self._iso(ended)
            commands = [
                {**item, "timestamp": item.get("timestamp", finished_iso)}
                if isinstance(item, dict) else {"label": "invalid-executor-record", "exit_code": 1, "timestamp": finished_iso}
                for item in commands
            ]
            try:
                bundle = self._pack_artifacts(artifacts)
            except Exception as exc:
                bundle = b"{}"
                status = "FAILED"
                error = f"artifact serialization failed: {type(exc).__name__}: {exc}"[:1000]
            result = {
                "schema": "sophyane.runner-result.v1", "runner_id": self.runner_id,
                "job_id": job_id, "kind": manifest["kind"],
                "requirement_ids": manifest["requirement_ids"],
                "verification_checks": manifest["verification_checks"],
                "source_sha256": manifest["source_sha256"],
                "archive_sha256": manifest["archive_sha256"], "status": status,
                "started_at": self._iso(started), "finished_at": self._iso(ended),
                "environment": {**self.environment_identity, "os": os.name,
                                "hostname": __import__("socket").gethostname()},
                "commands": commands,
                "artifacts": {name: sha256(data) for name, data in sorted(artifacts.items())},
                "artifact_bundle_sha256": sha256(bundle), "error": error,
            }
            canonical = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
            result["signature"] = self.auth.sign_response(200, f"/v1/jobs/{job_id}/result", canonical)
            with self._connect() as db:
                db.execute("UPDATE jobs SET state=?,updated=?,result=?,artifact=?,error=?,request=NULL WHERE job_id=?",
                           (status, ended, json.dumps(result, sort_keys=True), bundle, error, job_id))
            shutil.rmtree(job_root, ignore_errors=True)

    @staticmethod
    def _iso(timestamp: float) -> str:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()

    @staticmethod
    def _pack_artifacts(artifacts: dict[str, bytes]) -> bytes:
        # Artifact bundles are JSON to avoid unsafe extraction on the client.
        entries = {}
        total = 0
        for name, data in artifacts.items():
            if not isinstance(name, str) or not name or "/" in name or ".." in name or not isinstance(data, bytes):
                raise ValueError("executor returned invalid artifact")
            total += len(data)
            if total > 32 * 1024 * 1024:
                raise ValueError("artifact output exceeds 32 MiB")
            entries[name] = {"base64": base64.b64encode(data).decode(), "sha256": sha256(data)}
        return json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()

    def get(self, job_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            raise KeyError(job_id)
        return self._public_row(row)

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT state FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row:
                raise KeyError(job_id)
            if row["state"] in TERMINAL:
                return self.get(job_id)
            if row["state"] == "QUEUED":
                db.execute("UPDATE jobs SET state='CANCELLED',updated=? WHERE job_id=?", (self.clock(), job_id))
            with self._lock:
                event = self._locks.get(job_id)
                if event:
                    event.set()
        future = self._futures.get(job_id)
        if future:
            future.cancel()
        return self.get(job_id)

    def artifact(self, job_id: str) -> bytes:
        with self._connect() as db:
            row = db.execute("SELECT state,artifact FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            raise KeyError(job_id)
        if row["state"] not in TERMINAL or row["artifact"] is None:
            raise RuntimeError("job artifacts are not ready")
        return bytes(row["artifact"])


def build_server(service: RunnerService, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        server_version = "SophyaneRunner/1"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            # Avoid default access logs which can include untrusted path content.
            return

        def _respond(self, status: int, path: str, body: bytes, content_type: str = "application/json") -> None:
            signature = service.auth.sign_response(status, path, body)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Sophyane-Response-Signature", signature)
            self.end_headers()
            self.wfile.write(body)

        def _read_auth(self) -> bytes:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = MAX_BODY + 1
            if length < 0 or length > MAX_BODY:
                raise ValueError("request body exceeds limit")
            body = self.rfile.read(length)
            service.replay.verify(self.command, self.path, body, dict(self.headers.items()), service.auth)
            return body

        def _json(self, status: int, value: dict[str, Any]) -> None:
            body = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
            self._respond(status, self.path, body)

        def do_POST(self) -> None:
            try:
                body = self._read_auth()
                if self.path == "/v1/jobs":
                    value = service.submit(json.loads(body))
                    self._json(202, value)
                    return
                prefix = "/v1/jobs/"
                if self.path.startswith(prefix) and self.path.endswith("/cancel"):
                    job_id = self.path[len(prefix):-len("/cancel")].strip("/")
                    self._json(200, service.cancel(job_id))
                    return
                self._json(404, {"error": "not found"})
            except AuthenticationError as error:
                self._json(401, {"error": str(error)})
            except KeyError:
                self._json(404, {"error": "job not found"})
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._json(400, {"error": str(error)[:500]})
            except RuntimeError as error:
                self._json(409, {"error": str(error)[:500]})

        def do_GET(self) -> None:
            try:
                self._read_auth()
                prefix = "/v1/jobs/"
                if not self.path.startswith(prefix):
                    self._json(404, {"error": "not found"})
                    return
                suffix = self.path[len(prefix):]
                if suffix.endswith("/artifacts"):
                    job_id = suffix[:-len("/artifacts")]
                    data = service.artifact(job_id)
                    self._respond(200, self.path, data, "application/json")
                else:
                    self._json(200, service.get(suffix))
            except AuthenticationError as error:
                self._json(401, {"error": str(error)})
            except KeyError:
                self._json(404, {"error": "job not found"})
            except RuntimeError as error:
                self._json(409, {"error": str(error)[:500]})

    return ThreadingHTTPServer((host, port), Handler)
