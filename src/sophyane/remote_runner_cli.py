"""Launch a fixed-purpose Sophyane remote deployment runner host service."""
from __future__ import annotations

import hashlib
import os
import platform
import re
import signal
import socket
import subprocess
import sys
import threading
from pathlib import Path

from sophyane.remote_runner_executors import DockerComposeDeploymentExecutor, QemuFastAPIExecutor
from sophyane.remote_runner_service import RunnerService, build_server


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"required environment variable is missing: {name}")
    return value


def _secret(path: str | Path) -> bytes:
    target = Path(path)
    if not target.is_file() or target.stat().st_mode & 0o077:
        raise RuntimeError("runner secret file must exist and be mode 0600 or stricter")
    secret = target.read_bytes()
    if len(secret) < 32:
        raise RuntimeError("runner secret must contain at least 32 random bytes")
    return secret


def qemu_health_timeout_seconds() -> int:
    raw = os.environ.get("SOPHYANE_QEMU_HEALTH_TIMEOUT_SECONDS", "240").strip()
    try:
        timeout = int(raw)
    except ValueError as error:
        raise RuntimeError("SOPHYANE_QEMU_HEALTH_TIMEOUT_SECONDS must be between 60 and 1800") from error
    if not 60 <= timeout <= 1800:
        raise RuntimeError("SOPHYANE_QEMU_HEALTH_TIMEOUT_SECONDS must be between 60 and 1800")
    return timeout


def main() -> int:
    try:
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            raise RuntimeError("remote runner must run as an unprivileged dedicated service user")
        runner_id = _required("SOPHYANE_RUNNER_ID")
        secret = _secret(_required("SOPHYANE_RUNNER_SECRET_FILE"))
        kind = _required("SOPHYANE_REMOTE_JOB_KIND")
        root = Path(os.environ.get("SOPHYANE_RUNNER_ROOT", "/var/lib/sophyane-runner")).resolve()
        host = os.environ.get("SOPHYANE_RUNNER_LISTEN_HOST", "127.0.0.1")
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise RuntimeError("runner service must bind loopback and use a TLS reverse proxy")
        port = int(os.environ.get("SOPHYANE_RUNNER_PORT", "8765"))
        if kind == "docker-compose-deployment":
            docker = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True, timeout=15)
            if docker.returncode:
                raise RuntimeError("Docker Compose is unavailable or not authorized for this service account")
            version_match = re.search(r"(?:version\s+)?v?(\d+)\.(\d+)", docker.stdout + " " + docker.stderr, re.I)
            if not version_match or tuple(map(int, version_match.groups())) < (2, 24):
                raise RuntimeError("Docker Compose v2.24 or newer is required for safe port overrides")
            docker_info = subprocess.run(
                ["docker", "info", "--format", "{{json .SecurityOptions}}"],
                capture_output=True, text=True, timeout=20,
            )
            if docker_info.returncode or "rootless" not in docker_info.stdout.casefold():
                raise RuntimeError("Docker daemon must be reachable and run in rootless mode")
            executors = {kind: DockerComposeDeploymentExecutor(timeout=600, health_timeout=180)}
            execution_class = "docker-host"
            host_material = docker.stdout.strip() + " " + docker_info.stdout.strip()
        elif kind == "qemu-fastapi-deployment":
            image = Path(_required("SOPHYANE_QEMU_IMAGE")).resolve()
            expected = _required("SOPHYANE_QEMU_IMAGE_SHA256").lower()
            qemu_binary = os.environ.get("SOPHYANE_QEMU_BINARY", "qemu-system-x86_64")
            qemu_bios = os.environ.get("SOPHYANE_QEMU_BIOS")
            qemu_seed_iso = os.environ.get("SOPHYANE_QEMU_SEED_ISO")
            qemu_host_key_path = Path(_required("SOPHYANE_QEMU_SSH_HOST_PUBLIC_KEY")).resolve()
            if not qemu_host_key_path.is_file():
                raise RuntimeError("SOPHYANE_QEMU_SSH_HOST_PUBLIC_KEY must name the pinned guest SSH host public-key file")
            qemu_host_public_key = qemu_host_key_path.read_text(encoding="ascii").strip()
            if any(token in Path(qemu_binary).name.casefold() for token in ("aarch64", "arm64")):
                if not qemu_bios or not Path(qemu_bios).is_file():
                    raise RuntimeError("AArch64 QEMU requires SOPHYANE_QEMU_BIOS to name an installed firmware file")
            if qemu_seed_iso and not Path(qemu_seed_iso).is_file():
                raise RuntimeError("SOPHYANE_QEMU_SEED_ISO must name an existing cloud-init seed ISO")
            if not image.is_file() or _file_sha256(image) != expected:
                raise RuntimeError("configured QEMU image does not match its pinned SHA-256")
            if not shutil_which(qemu_binary):
                raise RuntimeError("configured QEMU executable is unavailable")
            executors = {kind: QemuFastAPIExecutor(
                image, expected, qemu_binary=qemu_binary, qemu_bios=qemu_bios,
                qemu_seed_iso=qemu_seed_iso, qemu_ssh_host_public_key=qemu_host_public_key,
                timeout=600, health_timeout=qemu_health_timeout_seconds(),
            )}
            execution_class = "qemu-host"
            host_material = expected + "\0" + hashlib.sha256(qemu_host_public_key.encode("ascii")).hexdigest()
        else:
            raise RuntimeError("SOPHYANE_REMOTE_JOB_KIND must select a supported fixed executor")
        try:
            machine_id = Path("/etc/machine-id").read_text(encoding="utf-8").strip()
        except OSError:
            machine_id = socket.gethostname()
        environment = {
            "runner_id": runner_id,
            "execution_class": execution_class,
            "real_execution": os.environ.get("SOPHYANE_REAL_EXECUTION") == "1",
            "host_fingerprint": hashlib.sha256(f"{runner_id}\0{machine_id}\0{host_material}".encode()).hexdigest(),
            "platform": platform.platform(),
        }
        service = RunnerService(root, runner_id, secret, executors,
                                workers=int(os.environ.get("SOPHYANE_RUNNER_WORKERS", "2")),
                                environment_identity=environment)
        server = build_server(service, host=host, port=port)
    except Exception as error:
        print(f"sophyane remote runner startup failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 2

    stopped = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        if not stopped.is_set():
            stopped.set()
            threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        service.close()
    return 0


def shutil_which(command: str) -> str | None:
    from shutil import which
    return which(command)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
