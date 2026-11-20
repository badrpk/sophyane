"""Security primitives and bounded source transfer for remote execution runners.

This module deliberately accepts named deployment recipes rather than arbitrary
commands. The RSI QEMU runner has a separate, network-isolated protocol.
"""
from __future__ import annotations

import hashlib
import hmac
import gzip
import json
import os
import re
import sqlite3
import tarfile
import time
from pathlib import Path, PurePosixPath
from typing import Any, Callable

MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_FILES = 10_000
MAX_EXPANDED_BYTES = 512 * 1024 * 1024
MAX_REQUEST_AGE_SECONDS = 300
JOB_KINDS = {"docker-compose-deployment", "qemu-fastapi-deployment"}
REQUIREMENT_IDS = {f"REQ-{number:03d}" for number in range(1, 20)}
JOB_REQUIREMENTS = {
    "docker-compose-deployment": ["REQ-008"],
    "qemu-fastapi-deployment": ["REQ-014", "REQ-018"],
}
VERIFICATION_CHECKS = {
    "docker-compose-deployment": [
        "compose-inspect", "compose-config", "compose-build", "compose-up", "api-health", "compose-health-status",
        "database-persistence-seed", "compose-api-restart", "api-after-restart",
        "compose-down-preserve-volume", "compose-up-after-restart", "database-persistence-check",
        "api-after-compose-restart", "postgres-volume-persistence",
        "compose-cleanup-remove-owned-volumes",
    ],
    "qemu-fastapi-deployment": [
        "qemu-overlay-create", "qemu-boot", "guest-9p-mounts", "ubuntu-boot-complete",
        "guest-ssh-authenticated", "guest-cloud-init-complete", "guest-dependencies-installed",
        "guest-database-migrations", "guest-dependencies-and-migration", "guest-saas-tests",
        "guest-fastapi-listening", "guest-fastapi-health-from-host",
        "guest-api-auth-enforcement-from-host",
    ],
}
EXCLUDED_PARTS = {
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache", ".tox", "dist", "build", "coverage",
}
EXCLUDED_NAMES = {
    ".env", ".env.local", ".env.production", ".netrc", ".npmrc", ".pypirc",
    "secrets.json", "credentials.json", "id_rsa", "id_ed25519",
    "TRACEABILITY.md", "REQUIREMENTS_TRACEABILITY.md",
}


class AuthenticationError(ValueError):
    """Request authentication, freshness, or replay check failed."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(method: str, path: str, timestamp: str, nonce: str, body: bytes) -> bytes:
    return "\n".join((method.upper(), path, timestamp, nonce, sha256(body))).encode("utf-8")


class RequestAuthenticator:
    def __init__(self, secret: bytes, *, clock: Callable[[], float] = time.time) -> None:
        if len(secret) < 32:
            raise ValueError("runner shared secret must contain at least 32 bytes")
        self.secret, self.clock = secret, clock

    def sign(
        self, method: str, path: str, body: bytes, *, nonce: str | None = None,
        timestamp: str | None = None,
    ) -> dict[str, str]:
        nonce = nonce or os.urandom(18).hex()
        timestamp = timestamp or str(int(self.clock()))
        signature = hmac.new(
            self.secret, _canonical(method, path, timestamp, nonce, body), hashlib.sha256
        ).hexdigest()
        return {
            "X-Sophyane-Timestamp": timestamp,
            "X-Sophyane-Nonce": nonce,
            "X-Sophyane-Signature": signature,
        }

    def verify(self, method: str, path: str, body: bytes, headers: dict[str, str]) -> None:
        normalized = {key.lower(): value for key, value in headers.items()}
        timestamp = normalized.get("x-sophyane-timestamp", "")
        nonce = normalized.get("x-sophyane-nonce", "")
        provided = normalized.get("x-sophyane-signature", "")
        try:
            numeric_timestamp = int(timestamp)
        except (ValueError, TypeError) as error:
            raise AuthenticationError("invalid timestamp") from error
        if abs(self.clock() - numeric_timestamp) > MAX_REQUEST_AGE_SECONDS:
            raise AuthenticationError("request expired")
        if not re.fullmatch(r"[a-f0-9]{24,64}", nonce):
            raise AuthenticationError("invalid nonce")
        expected = hmac.new(
            self.secret, _canonical(method, path, timestamp, nonce, body), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(provided, expected):
            raise AuthenticationError("invalid signature")

    def sign_response(self, status: int, path: str, body: bytes, *, timestamp: str | None = None) -> str:
        timestamp = timestamp or str(int(self.clock()))
        message = f"{status}\n{path}\n{timestamp}\n{sha256(body)}".encode()
        return timestamp + ":" + hmac.new(self.secret, message, hashlib.sha256).hexdigest()

    def verify_response(self, status: int, path: str, body: bytes, signature: str, *,
                        enforce_freshness: bool = True) -> None:
        try:
            timestamp, provided = signature.split(":", 1)
            numeric_timestamp = int(timestamp)
        except (ValueError, TypeError) as error:
            raise AuthenticationError("invalid response signature") from error
        if enforce_freshness and abs(self.clock() - numeric_timestamp) > MAX_REQUEST_AGE_SECONDS:
            raise AuthenticationError("response expired")
        message = f"{status}\n{path}\n{timestamp}\n{sha256(body)}".encode()
        expected = hmac.new(self.secret, message, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(provided, expected):
            raise AuthenticationError("invalid response signature")


class ReplayGuard:
    def __init__(self, path: str | Path, *, clock: Callable[[], float] = time.time) -> None:
        self.path, self.clock = str(path), clock
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS nonces (nonce TEXT PRIMARY KEY, seen REAL NOT NULL)")

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.execute("PRAGMA busy_timeout=15000")
        return connection

    def verify(self, method: str, path: str, body: bytes, headers: dict[str, str], auth: RequestAuthenticator) -> None:
        auth.verify(method, path, body, headers)
        nonce = next(value for key, value in headers.items() if key.lower() == "x-sophyane-nonce")
        now = self.clock()
        with self._connect() as db:
            db.execute("DELETE FROM nonces WHERE seen < ?", (now - MAX_REQUEST_AGE_SECONDS * 2,))
            try:
                db.execute("INSERT INTO nonces(nonce, seen) VALUES (?, ?)", (nonce, now))
            except sqlite3.IntegrityError as error:
                raise AuthenticationError("request replay detected") from error


def validate_job_manifest(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("job manifest must be an object")
    required = {"job_id", "kind", "requirement_ids", "source_sha256", "archive_sha256", "verification_checks"}
    if set(value) != required:
        raise ValueError("job manifest has missing or unsupported fields")
    if not isinstance(value["job_id"], str) or not re.fullmatch(r"job-[a-f0-9]{8,64}", value["job_id"]):
        raise ValueError("invalid job_id")
    if value["kind"] not in JOB_KINDS:
        raise ValueError("unsupported job kind")
    if value["verification_checks"] != VERIFICATION_CHECKS[value["kind"]]:
        raise ValueError("verification manifest does not match the fixed recipe")
    requirements = value["requirement_ids"]
    if not isinstance(requirements, list) or not requirements or any(item not in REQUIREMENT_IDS for item in requirements):
        raise ValueError("requirement IDs must be known and non-empty")
    if len(requirements) != len(set(requirements)):
        raise ValueError("duplicate requirement ID")
    if requirements != JOB_REQUIREMENTS[value["kind"]]:
        raise ValueError("requirement IDs do not match the fixed recipe")
    for key in ("source_sha256", "archive_sha256"):
        if not isinstance(value[key], str) or not re.fullmatch(r"[a-f0-9]{64}", value[key]):
            raise ValueError(f"invalid {key}")
    return dict(value)


def _eligible(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in EXCLUDED_PARTS or part.endswith("-venv") for part in relative.parts):
        return False
    if relative.parts[:2] == ("evidence", "remote-runs"):
        return False
    if (path.name in EXCLUDED_NAMES or path.name.startswith(".env.")
            or path.suffix.lower() in {".pem", ".p12", ".pfx", ".key"}):
        return False
    if path.is_symlink():
        return False
    return path.is_file()


def archive_project(root: str | Path, *, max_bytes: int = MAX_ARCHIVE_BYTES) -> tuple[bytes, dict[str, Any]]:
    base = Path(root).resolve()
    entries: list[tuple[str, bytes, str]] = []
    expanded = 0
    for path in sorted(base.rglob("*")):
        if not _eligible(path, base):
            continue
        relative = path.relative_to(base).as_posix()
        size = path.stat().st_size
        expanded += size
        if expanded > MAX_EXPANDED_BYTES:
            raise ValueError("project source exceeds expanded size limit")
        content = path.read_bytes()
        entries.append((relative, content, sha256(content)))
        if len(entries) > MAX_ARCHIVE_FILES:
            raise ValueError("project contains too many files")
    manifest = {
        "files": [name for name, _, _ in entries],
        "file_hashes": {name: digest for name, _, digest in entries},
        "source_sha256": sha256(json.dumps(
            [(name, digest) for name, _, digest in entries], separators=(",", ":")
        ).encode()),
    }
    output = __import__("io").BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", compresslevel=6, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as archive:
            for name, content, _ in entries:
                info = tarfile.TarInfo(name)
                info.size, info.mode, info.mtime = len(content), 0o644, 0
                archive.addfile(info, __import__("io").BytesIO(content))
    data = output.getvalue()
    if len(data) > max_bytes:
        raise ValueError("project archive exceeds size limit")
    manifest["archive_sha256"] = sha256(data)
    manifest["archive_size"] = len(data)
    return data, manifest


def source_tree_sha256(root: str | Path) -> str:
    base = Path(root).resolve()
    entries = []
    for path in sorted(base.rglob("*")):
        if _eligible(path, base):
            content = path.read_bytes()
            entries.append((path.relative_to(base).as_posix(), sha256(content)))
    return sha256(json.dumps(entries, separators=(",", ":")).encode())


def extract_project_archive(data: bytes, destination: str | Path, *, max_bytes: int = MAX_ARCHIVE_BYTES,
                            max_expanded: int = MAX_EXPANDED_BYTES) -> list[str]:
    if len(data) > max_bytes:
        raise ValueError("archive exceeds size limit")
    root = Path(destination).resolve()
    root.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    expanded = 0
    extracted: list[str] = []
    try:
        archive = tarfile.open(fileobj=__import__("io").BytesIO(data), mode="r:gz")
    except (tarfile.TarError, OSError) as error:
        raise ValueError("invalid source archive") from error
    with archive:
        members = archive.getmembers()
        if len(members) > MAX_ARCHIVE_FILES:
            raise ValueError("archive contains too many files")
        for member in members:
            name = member.name
            relative = PurePosixPath(name)
            if relative.is_absolute() or not name or ".." in relative.parts or "\\" in name:
                raise ValueError("unsafe archive path")
            if name in seen:
                raise ValueError("duplicate archive path")
            seen.add(name)
            if not member.isfile():
                raise ValueError("unsupported archive entry")
            expanded += member.size
            if expanded > max_expanded:
                raise ValueError("expanded archive exceeds size limit")
            target = (root / Path(*relative.parts)).resolve()
            try:
                target.relative_to(root)
            except ValueError as error:
                raise ValueError("unsafe archive path") from error
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("invalid archive entry")
            remaining = member.size
            with target.open("xb") as output:
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("truncated archive entry")
                    output.write(chunk)
                    remaining -= len(chunk)
                if stream.read(1):
                    raise ValueError("archive entry exceeds declared size")
            os.chmod(target, 0o600)
            extracted.append(name)
    return extracted
