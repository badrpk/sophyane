"""Fixed Docker Compose and QEMU application deployment recipes."""
from __future__ import annotations

import hashlib
import json
import os
import re
import resource
import base64
import binascii
import secrets
import shlex
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


@dataclass
class CommandResult:
    argv: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    cancelled: bool = False


class BoundedCommandRunner:
    """Run a process group with wall-time, CPU, memory, file and output bounds."""

    def __init__(self, *, timeout: int = 600, cpu_seconds: int = 900,
                 memory_bytes: int = 2 * 1024**3, output_bytes: int = 2 * 1024**2,
                 address_space_bytes: int | None = None, data_bytes: int | None = None,
                 process_limit: int = 128) -> None:
        self.timeout, self.cpu_seconds = timeout, cpu_seconds
        self.memory_bytes, self.output_bytes = memory_bytes, output_bytes
        self.address_space_bytes = address_space_bytes or memory_bytes
        self.data_bytes, self.process_limit = data_bytes, process_limit

    def __call__(self, argv: list[str], *, cwd: Path, env: dict[str, str],
                 cancel: threading.Event) -> CommandResult:
        started = time.monotonic()
        with tempfile.TemporaryFile() as output:
            def limits() -> None:
                resource.setrlimit(resource.RLIMIT_CPU, (self.cpu_seconds, self.cpu_seconds))
                if hasattr(resource, "RLIMIT_AS"):
                    resource.setrlimit(resource.RLIMIT_AS, (self.address_space_bytes, self.address_space_bytes))
                if self.data_bytes is not None and hasattr(resource, "RLIMIT_DATA"):
                    resource.setrlimit(resource.RLIMIT_DATA, (self.data_bytes, self.data_bytes))
                resource.setrlimit(resource.RLIMIT_FSIZE, (self.output_bytes * 4, self.output_bytes * 4))
                resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
                if hasattr(resource, "RLIMIT_NPROC"):
                    resource.setrlimit(resource.RLIMIT_NPROC, (self.process_limit, self.process_limit))

            process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.STDOUT, start_new_session=True,
                                       preexec_fn=limits if os.name == "posix" else None)
            timed_out = cancelled = False
            deadline = started + self.timeout
            while process.poll() is None:
                if cancel.is_set():
                    cancelled = True
                elif time.monotonic() >= deadline:
                    timed_out = True
                if cancelled or timed_out:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                        process.wait(timeout=3)
                    except (ProcessLookupError, subprocess.TimeoutExpired):
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    break
                time.sleep(0.1)
            code = process.wait()
            output.seek(max(0, output.tell() - self.output_bytes))
            text = output.read(self.output_bytes).decode("utf-8", errors="replace")
        return CommandResult(list(argv), code, text, "", time.monotonic() - started, timed_out, cancelled)


class DeploymentExecutor:
    def __init__(self, *, command_runner: Callable[..., CommandResult] | None = None,
                 http_get: Callable[[str, float], tuple[int, bytes]] | None = None,
                 timeout: int = 600, health_timeout: int = 120) -> None:
        self.run = command_runner or BoundedCommandRunner(timeout=timeout)
        self.http_get = http_get or self._http_get
        self.timeout, self.health_timeout = timeout, health_timeout

    @staticmethod
    def _http_get(url: str, timeout: float) -> tuple[int, bytes]:
        request = urllib.request.Request(url, headers={"User-Agent": "Sophyane-Remote-Runner/1"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read(2 * 1024 * 1024)
        except urllib.error.HTTPError as error:
            return error.code, error.read(2 * 1024 * 1024)

    def _wait_http(self, url: str, cancel: threading.Event, *, expected: int = 200,
                   window_seconds: float | None = None) -> tuple[bool, str]:
        deadline = time.monotonic() + (self.health_timeout if window_seconds is None else window_seconds)
        last = "no response"
        while time.monotonic() < deadline and not cancel.is_set():
            try:
                status, body = self.http_get(url, 3)
                last = f"HTTP {status} ({body[:256].decode('utf-8', errors='replace')})"
                if status == expected and (not url.endswith("/healthz") or body.strip() == b'{"status":"ok"}'):
                    return True, last
            except (OSError, TimeoutError) as error:
                last = f"{type(error).__name__}: {error}"
            cancel.wait(0.5)
        return False, last

    @staticmethod
    def _record(result: CommandResult, label: str, *, redact: tuple[str, ...] = ()) -> dict[str, Any]:
        output = result.stdout[-64_000:]
        error = result.stderr[-64_000:]
        for secret in redact:
            if secret:
                output = output.replace(secret, "[REDACTED]")
                error = error.replace(secret, "[REDACTED]")
        return {"label": label, "argv": result.argv, "exit_code": result.exit_code,
                "started_or_elapsed_seconds": round(result.duration_seconds, 3),
                "timed_out": result.timed_out, "cancelled": result.cancelled, "timestamp":
                    datetime.now(timezone.utc).isoformat(), "output": output, "stderr": error}

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()


class DockerComposeDeploymentExecutor(DeploymentExecutor):
    """Deploy one project under an isolated Compose name and verify DB persistence."""

    def __call__(self, workspace: Path, manifest: dict[str, Any], cancel: threading.Event) -> dict[str, Any]:
        compose = next((workspace / name for name in ("compose.yaml", "compose.yml", "docker-compose.yml")
                        if (workspace / name).is_file()), None)
        if compose is None:
            return {"passed": False, "error": "Compose manifest is missing", "commands": [], "artifacts": {}}
        project = "soph-" + re.sub("[^a-z0-9]", "", manifest["job_id"].lower())[-24:]
        override = workspace / ".sophyane-resource-override.yaml"
        compose_base = ["docker", "compose", "--project-name", project, "--file", compose.name]
        password, jwt_secret = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        env = dict(os.environ)
        env.update({"POSTGRES_PASSWORD": password, "JWT_SECRET": jwt_secret,
                    "COMPOSE_DISABLE_ENV_FILE": "1", "DOCKER_BUILDKIT": "1"})
        commands: list[dict[str, Any]] = []
        artifacts: dict[str, bytes] = {}
        passed, error, did_start = False, "", False
        probe = "sophyane_remote_" + secrets.token_hex(12)

        def command(label: str, args: list[str], *, timeout: int | None = None) -> CommandResult:
            nonlocal error
            if cancel.is_set():
                return CommandResult(args, -signal.SIGTERM, "", "cancelled", 0, cancelled=True)
            previous = getattr(self.run, "timeout", None)
            if timeout and previous is not None:
                self.run.timeout = timeout
            try:
                result = self.run(args, cwd=workspace, env=env, cancel=cancel)
            finally:
                if timeout and previous is not None:
                    self.run.timeout = previous
            commands.append(self._record(result, label, redact=(password, jwt_secret)))
            if result.exit_code != 0 or result.timed_out or result.cancelled:
                error = f"{label} failed (exit {result.exit_code})"
            return result

        try:
            result = command("compose-inspect", compose_base + ["config", "--format", "json"])
            if result.exit_code:
                return {"passed": False, "error": error, "commands": commands, "artifacts": artifacts}
            try:
                initial = json.loads(result.stdout)
                services = initial.get("services")
                if not isinstance(services, dict) or not {"api", "database"} <= set(services):
                    raise ValueError("Compose must define api and database services")
                if not any(isinstance(port, dict) and int(port.get("target", -1)) == 8000
                           for port in services["api"].get("ports", [])):
                    raise ValueError("api service must expose container port 8000")
            except (ValueError, TypeError, AttributeError) as exc:
                return {"passed": False, "error": f"unsupported Compose model: {exc}",
                        "commands": commands, "artifacts": artifacts}
            with socket.socket() as port_socket:
                port_socket.bind(("127.0.0.1", 0))
                host_port = port_socket.getsockname()[1]
            lines = ["services:"]
            for name in services:
                if not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
                    return {"passed": False, "error": "Compose contains an invalid service name",
                            "commands": commands, "artifacts": artifacts}
                lines.extend([f"  {name}:", "    cpus: '1.0'", "    mem_limit: 1g", "    pids_limit: 128"])
                if name == "api":
                    lines.extend(["    ports: !override", f'      - "127.0.0.1:{host_port}:8000"'])
            lines.extend(["networks:", "  default:", "    internal: true"])
            override.write_text("\n".join(lines) + "\n", encoding="utf-8")
            os.chmod(override, 0o600)
            compose_args = compose_base + ["--file", override.name]
            result = command("compose-config", compose_args + ["config", "--format", "json"])
            if result.exit_code:
                return {"passed": False, "error": error, "commands": commands, "artifacts": artifacts}
            try:
                self._validate_config(json.loads(result.stdout), workspace, host_port)
            except (ValueError, TypeError, AttributeError) as exc:
                return {"passed": False, "error": f"Compose isolation validation failed: {exc}",
                        "commands": commands, "artifacts": artifacts}
            for label, args in (("compose-build", compose_args + ["build", "--pull=false", "--network=none"]),
                                ("compose-up", compose_args + ["up", "--detach", "--no-build", "--pull", "never"])):
                result = command(label, args)
                if label == "compose-up":
                    did_start = result.exit_code == 0
                if result.exit_code:
                    return {"passed": False, "error": error, "commands": commands, "artifacts": artifacts}
            api_url = f"http://127.0.0.1:{host_port}"
            ready, diagnostic = self._wait_http(api_url + "/healthz", cancel)
            commands.append({"label": "api-health", "url": api_url + "/healthz", "exit_code": int(not ready),
                             "timestamp": self._timestamp(), "diagnostic": diagnostic})
            if not ready:
                return {"passed": False, "error": "API health check failed: " + diagnostic,
                        "commands": commands, "artifacts": artifacts}
            result = command("compose-health-status", compose_args + ["ps", "--format", "json"])
            try:
                rows = json.loads(result.stdout)
                if isinstance(rows, dict):
                    rows = [rows]
                states = {str(x.get("Service", x.get("service", ""))): x for x in rows if isinstance(x, dict)}
                healthy = all(states.get(name, {}).get("State", states.get(name, {}).get("state")) == "running"
                              and states.get(name, {}).get("Health", states.get(name, {}).get("health")) == "healthy"
                              for name in ("api", "database"))
            except (ValueError, TypeError, AttributeError):
                healthy = False
            commands[-1]["exit_code"] = 0 if healthy and result.exit_code == 0 else 1
            if not healthy or result.exit_code:
                return {"passed": False, "error": "Compose API/database health checks did not report healthy",
                        "commands": commands, "artifacts": artifacts}
            result = command("database-persistence-seed", compose_args + ["exec", "-T", "database", "psql", "-U", "inventory", "-d", "inventory", "-v", "ON_ERROR_STOP=1", "-c",
                f"CREATE TABLE IF NOT EXISTS sophyane_runner_probe(id text PRIMARY KEY, created timestamptz DEFAULT now()); INSERT INTO sophyane_runner_probe(id) VALUES('{probe}') ON CONFLICT DO NOTHING;"])
            if result.exit_code:
                return {"passed": False, "error": error, "commands": commands, "artifacts": artifacts}
            result = command("compose-api-restart", compose_args + ["restart", "api"])
            if result.exit_code:
                return {"passed": False, "error": error, "commands": commands, "artifacts": artifacts}
            ready, diagnostic = self._wait_http(api_url + "/healthz", cancel)
            commands.append({"label": "api-after-restart", "exit_code": 0 if ready else 1,
                             "timestamp": self._timestamp(), "diagnostic": diagnostic})
            if not ready:
                return {"passed": False, "error": "API restart health check failed", "commands": commands, "artifacts": artifacts}
            result = command("compose-down-preserve-volume", compose_args + ["down", "--remove-orphans"])
            if result.exit_code:
                return {"passed": False, "error": error, "commands": commands, "artifacts": artifacts}
            did_start = False
            result = command("compose-up-after-restart", compose_args + ["up", "--detach", "--no-build", "--pull", "never"])
            did_start = result.exit_code == 0
            if result.exit_code:
                return {"passed": False, "error": error, "commands": commands, "artifacts": artifacts}
            ready, diagnostic = self._wait_http(api_url + "/healthz", cancel)
            result = command("database-persistence-check", compose_args + ["exec", "-T", "database", "psql", "-U", "inventory", "-d", "inventory", "-v", "ON_ERROR_STOP=1", "-Atc",
                f"SELECT count(*) FROM sophyane_runner_probe WHERE id='{probe}';"])
            persistence = result.exit_code == 0 and result.stdout.strip().endswith("1")
            commands.append({"label": "api-after-compose-restart", "exit_code": 0 if ready else 1,
                             "timestamp": self._timestamp(), "diagnostic": diagnostic})
            commands.append({"label": "postgres-volume-persistence", "exit_code": 0 if persistence else 1,
                             "timestamp": self._timestamp(),
                             "marker_hash": hashlib.sha256(probe.encode()).hexdigest()})
            if not ready or not persistence:
                return {"passed": False, "error": "health or PostgreSQL volume persistence check failed",
                        "commands": commands, "artifacts": artifacts}
            passed = True
        except (OSError, RuntimeError, ValueError) as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            if did_start:
                cleanup = self.run(compose_args + ["down", "--volumes", "--remove-orphans"],
                                   cwd=workspace, env=env, cancel=threading.Event())
                commands.append(self._record(cleanup, "compose-cleanup-remove-owned-volumes"))
                if cleanup.exit_code != 0:
                    passed, error = False, "Compose cleanup failed"
            override.unlink(missing_ok=True)
        if passed:
            artifacts["docker-compose-results.json"] = json.dumps({"commands": commands}, indent=2).encode()
        return {"passed": passed, "error": error, "commands": commands, "artifacts": artifacts}

    @staticmethod
    def _validate_config(config: dict[str, Any], workspace: Path, host_port: int) -> None:
        services = config.get("services")
        if not isinstance(services, dict) or not {"api", "database"} <= set(services):
            raise ValueError("normalized Compose model lacks api or database")
        for name, service in services.items():
            if any(service.get(key) for key in ("privileged", "devices", "cap_add", "device_cgroup_rules", "runtime",
                                                  "volumes_from", "userns_mode", "cgroup", "security_opt")):
                raise ValueError(f"service {name} requests host-level privilege or devices")
            if service.get("network_mode") in {"host", "container:host"} or service.get("pid") == "host" or service.get("ipc") == "host":
                raise ValueError(f"service {name} requests host namespaces")
            if float(service.get("cpus", 0)) > 1.0 or float(service.get("cpus", 0)) <= 0:
                raise ValueError(f"service {name} has no bounded CPU limit")
            memory = service.get("mem_limit", 0)
            if isinstance(memory, str):
                match = re.fullmatch(r"(\d+)([kmg]?)", memory.strip().lower())
                if not match:
                    raise ValueError(f"service {name} has an invalid memory limit")
                memory = int(match.group(1)) * {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}[match.group(2)]
            if not 0 < int(memory) <= 1024**3 or not 1 <= int(service.get("pids_limit", 0)) <= 128:
                raise ValueError(f"service {name} has no bounded memory/PID limits")
            for volume in service.get("volumes", []):
                if isinstance(volume, dict) and volume.get("type") == "bind":
                    try:
                        Path(str(volume.get("source", ""))).resolve().relative_to(workspace.resolve())
                    except ValueError as error:
                        raise ValueError(f"service {name} bind-mounts outside the job workspace") from error
            for port in service.get("ports", []):
                if (name != "api" or str(port.get("host_ip", "")) != "127.0.0.1"
                        or int(port.get("published", -1)) != host_port or int(port.get("target", -1)) != 8000):
                    raise ValueError(f"service {name} has a non-loopback or unexpected published port")
            if service.get("build"):
                context = Path(str(service["build"].get("context", workspace))).resolve()
                try:
                    context.relative_to(workspace.resolve())
                except ValueError as error:
                    raise ValueError(f"service {name} builds from outside the job workspace") from error
        networks = config.get("networks", {})
        if not isinstance(networks, dict) or not networks:
            raise ValueError("Compose has no isolated networks")
        for name, network in networks.items():
            if network.get("internal") is not True or network.get("external"):
                raise ValueError(f"Compose network {name} is not internal")
        for group in ("volumes", "configs", "secrets"):
            for name, definition in config.get(group, {}).items():
                if isinstance(definition, dict) and definition.get("external"):
                    raise ValueError(f"external Compose {group[:-1]} {name} is forbidden")


class QemuFastAPIExecutor(DeploymentExecutor):
    """Run the generated project in a pinned Linux guest with an isolated overlay."""

    def __init__(self, image: str | Path, image_sha256: str, *, qemu_binary: str = "qemu-system-x86_64",
                 qemu_bios: str | Path | None = None, qemu_seed_iso: str | Path | None = None,
                 qemu_ssh_host_public_key: str | None = None,
                 app_port: int = 8000, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.image, self.image_sha256 = Path(image).resolve(), image_sha256
        self.qemu_binary, self.app_port = qemu_binary, app_port
        self.qemu_bios = Path(qemu_bios).resolve() if qemu_bios else None
        self.qemu_seed_iso = Path(qemu_seed_iso).resolve() if qemu_seed_iso else None
        self.qemu_ssh_host_public_key = qemu_ssh_host_public_key

    def _known_hosts_contents(self, port: int) -> str:
        """Bind the loopback-forwarded SSH endpoint to the configured trusted guest key."""
        if not isinstance(self.qemu_ssh_host_public_key, str) or len(self.qemu_ssh_host_public_key) > 16_384:
            raise ValueError("trusted SSH host public key is required")
        parts = self.qemu_ssh_host_public_key.strip().split()
        if len(parts) < 2 or parts[0] != "ssh-ed25519":
            raise ValueError("invalid trusted SSH host public key")
        try:
            blob = base64.b64decode(parts[1], validate=True)
        except (ValueError, binascii.Error) as error:
            raise ValueError("invalid trusted SSH host public key") from error
        # Validate the SSH wire encoding, not just the textual key type.
        key_type = b"ssh-ed25519"
        if (len(blob) != 4 + len(key_type) + 4 + 32
                or int.from_bytes(blob[:4], "big") != len(key_type)
                or blob[4:4 + len(key_type)] != key_type
                or int.from_bytes(blob[4 + len(key_type):8 + len(key_type)], "big") != 32):
            raise ValueError("invalid trusted SSH host public key")
        if not 1 <= port <= 65535:
            raise ValueError("invalid forwarded SSH port")
        return f"[127.0.0.1]:{port} {parts[0]} {parts[1]}\n"

    def _qemu_platform_args(self, overlay: Path) -> tuple[list[str], str]:
        """Build the boot and NIC arguments for the configured guest architecture."""
        binary_name = Path(self.qemu_binary).name.casefold()
        if "aarch64" in binary_name or "arm64" in binary_name:
            if self.qemu_bios is None:
                raise ValueError("SOPHYANE_QEMU_BIOS is required for an AArch64 guest")
            return (
                ["-machine", "virt", "-accel", "tcg,thread=multi", "-cpu", "cortex-a72",
                 "-bios", str(self.qemu_bios),
                 "-drive", f"if=none,file={overlay},format=qcow2,id=hd0",
                 "-device", "virtio-blk-device,drive=hd0"],
                "virtio-net-device",
            )
        return (["-machine", "accel=tcg", "-cpu", "max", "-drive",
                 f"file={overlay},if=virtio,format=qcow2"], "virtio-net-pci")

    def _qemu_img_command_runner(self) -> Callable[..., CommandResult]:
        if not isinstance(self.run, BoundedCommandRunner):
            return self.run
        return BoundedCommandRunner(timeout=self.run.timeout, cpu_seconds=self.run.cpu_seconds,
                                    memory_bytes=self.run.memory_bytes, output_bytes=self.run.output_bytes,
                                    address_space_bytes=16 * 1024**3, data_bytes=self.run.memory_bytes,
                                    process_limit=max(self.run.process_limit, 512))

    def _ssh(self, port: int, private_key: Path, command: str, *, known_hosts: Path, cwd: Path,
             cancel: threading.Event, timeout: int = 15) -> CommandResult:
        argv = [shutil.which("ssh") or "ssh", "-F", "/dev/null", "-i", str(private_key), "-p", str(port),
                "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", "IdentityAgent=none",
                "-o", "PreferredAuthentications=publickey", "-o", "PubkeyAuthentication=yes",
                "-o", "PasswordAuthentication=no", "-o", "KbdInteractiveAuthentication=no",
                "-o", "StrictHostKeyChecking=yes",
                "-o", f"UserKnownHostsFile={known_hosts}", "-o", "GlobalKnownHostsFile=/dev/null",
                "-o", "HostKeyAlgorithms=ssh-ed25519", "-o", "UpdateHostKeys=no",
                "-o", "ConnectTimeout=4", "-o", "LogLevel=ERROR",
                "sophyane@127.0.0.1", command]
        previous = getattr(self.run, "timeout", None)
        if previous is not None:
            self.run.timeout = timeout
        try:
            return self.run(argv, cwd=cwd, env=dict(os.environ), cancel=cancel)
        finally:
            if previous is not None:
                self.run.timeout = previous

    @staticmethod
    def _classify_ssh_failure(exit_code: int, stderr: str, *, timed_out: bool = False) -> str:
        message = stderr.casefold()
        if timed_out:
            return "probe_timeout"
        if any(token in message for token in ("connection refused", "connection timed out", "no route to host",
                                               "network is unreachable", "connection reset")):
            return "connection_failure"
        if "permission denied" in message and "publickey" in message:
            return "key_rejected"
        if "host key verification failed" in message or "remote host identification has changed" in message:
            return "host_key_rejected"
        if any(token in message for token in ("account is currently not available", "shell request failed",
                                               "account expired", "account is locked")):
            return "account_restriction"
        if exit_code not in (0, 255):
            return "remote_command_failure"
        return "ssh_transport_or_protocol_failure"

    @staticmethod
    def _guest_console(log: Any) -> bytes:
        try:
            log.flush()
            return os.pread(log.fileno(), 512 * 1024, 0)
        except (AttributeError, OSError):
            log.flush()
            position = log.tell()
            log.seek(0)
            output = log.read(512 * 1024)
            log.seek(position)
            return output

    @staticmethod
    def _readiness_report(raw: str) -> dict[str, Any]:
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) and isinstance(value.get("stages", {}), dict) else {}
        except (ValueError, TypeError):
            return {}

    def __call__(self, workspace: Path, manifest: dict[str, Any], cancel: threading.Event) -> dict[str, Any]:
        if not self.image.is_file() or _sha256_file(self.image) != self.image_sha256:
            return {"passed": False, "error": "pinned QEMU guest image is absent or has wrong digest", "commands": [], "artifacts": {}}
        if self.qemu_seed_iso is not None and not self.qemu_seed_iso.is_file():
            return {"passed": False, "error": "configured QEMU cloud-init seed ISO is absent", "commands": [], "artifacts": {}}
        qemu = shutil.which(self.qemu_binary)
        ssh_keygen = shutil.which("ssh-keygen")
        ssh = shutil.which("ssh")
        if not qemu or not ssh_keygen or not ssh:
            return {"passed": False, "error": "QEMU, ssh-keygen, and ssh are required", "commands": [], "artifacts": {}}
        ports: list[int] = []
        for _ in range(2):
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                ports.append(sock.getsockname()[1])
        ssh_port, app_port = ports
        try:
            known_hosts_contents = self._known_hosts_contents(ssh_port)
        except ValueError as error:
            return {"passed": False, "error": str(error), "commands": [], "artifacts": {}}
        overlay = workspace.parent / (workspace.name + ".qcow2")
        output_dir = workspace.parent / (workspace.name + "-qemu-output")
        key_dir = workspace.parent / (workspace.name + "-qemu-ssh")
        output_dir.mkdir(mode=0o700)
        key_dir.mkdir(mode=0o700)
        key_file, known_hosts_file, runner_env = (
            key_dir / "runner_ed25519", key_dir / "known_hosts", output_dir / "runner.env"
        )
        known_hosts_file.write_text(known_hosts_contents, encoding="ascii")
        os.chmod(known_hosts_file, 0o600)
        app_secret = secrets.token_urlsafe(48)
        commands: list[dict[str, Any]] = []
        artifacts: dict[str, bytes] = {}
        process: subprocess.Popen[Any] | None = None
        passed = False
        error = "QEMU guest readiness failed"

        def write_env(public_key: str) -> None:
            runner_env.write_text(
                "APP_ENV=production\nDATABASE_URL=postgresql:///inventory\n"
                f"JWT_SECRET={shlex.quote(app_secret)}\nSOPHYANE_PROJECT=/mnt/sophyane-input\n"
                f"SOPHYANE_OUTPUT=/mnt/sophyane-output\nSOPHYANE_RUNNER_SSH_PUBLIC_KEY={shlex.quote(public_key)}\n",
                encoding="utf-8")
            os.chmod(runner_env, 0o600)

        def ssh_probe(label: str, command: str, *, timeout: int = 15) -> CommandResult:
            result = self._ssh(ssh_port, key_file, command, known_hosts=known_hosts_file,
                               cwd=workspace, cancel=cancel, timeout=timeout)
            commands.append(self._record(result, label))
            return result

        def stage_wait(label: str, stage: str, deadline: float) -> bool:
            last = "guest stage report unavailable"
            while time.monotonic() < deadline and not cancel.is_set():
                result = self._ssh(ssh_port, key_file, "cat /mnt/sophyane-output/qemu-readiness.json 2>/dev/null || true",
                                   known_hosts=known_hosts_file,
                                   cwd=workspace, cancel=cancel, timeout=min(15, max(2, int(deadline - time.monotonic()))))
                report = self._readiness_report(result.stdout)
                current = report.get("stages", {}).get(stage, {})
                state = current.get("state") if isinstance(current, dict) else None
                last = str(current.get("diagnostic", "stage has not reported")) if isinstance(current, dict) else "stage has not reported"
                if state in {"passed", "failed"}:
                    commands.append({"label": label, "exit_code": 0 if state == "passed" else 1,
                                     "stage": stage, "diagnostic": last,
                                     "timestamp": current.get("timestamp") or self._timestamp()})
                    return state == "passed"
                cancel.wait(0.5)
            commands.append({"label": label, "exit_code": 1, "stage": stage, "diagnostic": last,
                             "timestamp": self._timestamp(), "timed_out": not cancel.is_set(),
                             "cancelled": cancel.is_set()})
            return False

        try:
            result = self._qemu_img_command_runner()(
                [ssh_keygen, "-q", "-t", "ed25519", "-N", "", "-C", manifest["job_id"], "-f", str(key_file)],
                cwd=workspace, env=dict(os.environ), cancel=cancel)
            commands.append(self._record(result, "qemu-ephemeral-ssh-key-create"))
            if result.exit_code or not key_file.is_file():
                error = "could not create isolated per-job SSH credentials"
                return {"passed": False, "error": error, "commands": commands, "artifacts": artifacts}
            os.chmod(key_file, 0o600)
            public_key = key_file.with_suffix(".pub").read_text(encoding="utf-8").strip()
            write_env(public_key)
            result = self._qemu_img_command_runner()(
                ["qemu-img", "create", "-f", "qcow2", "-F", "qcow2", "-b", str(self.image), str(overlay)],
                cwd=workspace, env=dict(os.environ), cancel=cancel)
            commands.append(self._record(result, "qemu-overlay-create"))
            if result.exit_code:
                error = "could not create isolated QEMU overlay"
                return {"passed": False, "error": error, "commands": commands, "artifacts": artifacts}
            platform_args, network_device = self._qemu_platform_args(overlay)
            qemu_argv = [qemu, *platform_args, "-m", "2048", "-smp", "2",
                         "-nographic", "-no-reboot",
                         "-virtfs", f"local,path={workspace},mount_tag=sophyane,security_model=mapped-xattr,readonly=on",
                         "-virtfs", f"local,path={output_dir},mount_tag=sophyane-output,security_model=mapped-xattr",
                         "-netdev", f"user,id=net0,restrict=on,hostfwd=tcp:127.0.0.1:{ssh_port}-:22,hostfwd=tcp:127.0.0.1:{app_port}-:{self.app_port}",
                         "-device", f"{network_device},netdev=net0"]
            if self.qemu_seed_iso is not None:
                qemu_argv.extend([
                    "-drive", f"if=none,file={self.qemu_seed_iso},format=raw,readonly=on,id=cloudinit",
                    "-device", "virtio-blk-device,drive=cloudinit",
                ])
            started = time.monotonic()
            with tempfile.TemporaryFile() as log:
                process = subprocess.Popen(qemu_argv, cwd=workspace, env=dict(os.environ), stdin=subprocess.DEVNULL,
                                           stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                commands.append({"label": "qemu-process-alive", "exit_code": 0 if process.poll() is None else 1,
                                 "argv": qemu_argv, "pid": process.pid, "image_sha256": self.image_sha256,
                                 "timestamp": self._timestamp(),
                                 "guest_memory_mib": 2048, "guest_cpus": 2})
                # This stage records successful creation of the QEMU process.
                # Guest readiness has its own ubuntu-boot-complete record and
                # must not retroactively turn a successful launch into a QEMU
                # launch failure.
                boot_record = {"label": "qemu-boot", "argv": qemu_argv, "exit_code": 0,
                               "timestamp": self._timestamp(),
                               "host_forward": f"127.0.0.1:{app_port}->{self.app_port}",
                               "ssh_forward": f"127.0.0.1:{ssh_port}->22"}
                commands.append(boot_record)
                deadline = started + self.health_timeout
                boot_deadline = min(deadline, started + 600)
                ssh_service_ready = False
                ninep_mounts_ready = False
                multiuser_console = False
                boot_ok = False
                ssh_ok = False
                boot_diag = "waiting for guest SSH provisioning and multi-user target"
                last_ssh = "SSH probe not attempted: guest key provisioning stage has not passed"
                ssh_result: CommandResult | None = None
                while time.monotonic() < boot_deadline and not cancel.is_set():
                    if process.poll() is not None:
                        boot_diag = f"QEMU exited before Ubuntu readiness (exit {process.returncode})"
                        last_ssh = boot_diag
                        break
                    console = self._guest_console(log)
                    multiuser_console = (b"Reached target multi-user.target" in console
                                         or b"Reached target Multi-User System" in console)
                    readiness_path = output_dir / "qemu-readiness.json"
                    if readiness_path.is_file():
                        try:
                            report = self._readiness_report(readiness_path.read_text(encoding="utf-8"))
                            stages = report.get("stages", {})
                            output_mount = stages.get("guest_output_mount", {})
                            source_mount = stages.get("guest_source_mount", {})
                            mount_failed = any(
                                isinstance(stage, dict) and stage.get("state") == "failed"
                                for stage in (output_mount, source_mount)
                            )
                            ninep_mounts_ready = all(
                                isinstance(stage, dict) and stage.get("state") == "passed"
                                for stage in (output_mount, source_mount)
                            )
                            existing_mount_check = next(
                                (item for item in commands if item.get("label") == "guest-9p-mounts"), None
                            )
                            if ninep_mounts_ready and existing_mount_check is None:
                                commands.append({"label": "guest-9p-mounts", "exit_code": 0,
                                                 "timestamp": self._timestamp(),
                                                 "diagnostic": "guest confirmed read-only source and writable output 9p mounts"})
                            elif mount_failed and existing_mount_check is None:
                                diagnostics = "; ".join(
                                    str(stage.get("diagnostic", "mount failed"))
                                    for stage in (output_mount, source_mount)
                                    if isinstance(stage, dict) and stage.get("state") == "failed"
                                )
                                commands.append({"label": "guest-9p-mounts", "exit_code": 1,
                                                 "timestamp": self._timestamp(), "diagnostic": diagnostics})
                                boot_diag = "guest 9p mount failed: " + diagnostics
                                break
                            stage = report.get("stages", {}).get("guest_ssh_service", {})
                            ssh_service_ready = isinstance(stage, dict) and stage.get("state") == "passed"
                            if isinstance(stage, dict) and stage.get("state") == "failed":
                                last_ssh = str(stage.get("diagnostic", "guest SSH provisioning failed"))
                        except OSError:
                            pass
                    if ssh_service_ready and ninep_mounts_ready and multiuser_console:
                        ssh_result = self._ssh(ssh_port, key_file, "id", cwd=workspace,
                                               known_hosts=known_hosts_file, cancel=cancel, timeout=10)
                        last_ssh = ssh_result.stdout.strip() or ssh_result.stderr[-1000:] or f"exit {ssh_result.exit_code}"
                        if ssh_result.exit_code == 0 and re.search(r"\buid=\d+\(sophyane\)", ssh_result.stdout):
                            ssh_ok = True
                            target = self._ssh(ssh_port, key_file, "systemctl is-active multi-user.target",
                                               known_hosts=known_hosts_file, cwd=workspace,
                                               cancel=cancel, timeout=10)
                            boot_diag = target.stdout.strip() or target.stderr[-1000:] or f"exit {target.exit_code}"
                            if target.exit_code == 0 and target.stdout.strip() == "active":
                                boot_ok = True
                                break
                        elif ssh_result.exit_code == 255:
                            last_ssh = ssh_result.stderr[-1000:] or "SSH transport/authentication failed (exit 255)"
                    cancel.wait(0.5)
                commands.append({"label": "ubuntu-boot-complete", "exit_code": 0 if boot_ok else 1,
                                 "timestamp": self._timestamp(),
                                 "diagnostic": "authenticated systemctl confirmed multi-user.target active" if boot_ok else boot_diag,
                                 "timed_out": not boot_ok and not cancel.is_set(), "cancelled": cancel.is_set()})
                ssh_stage = {"label": "guest-ssh-authenticated", "exit_code": 0 if ssh_ok else 1,
                             "timestamp": self._timestamp(), "diagnostic": last_ssh,
                             "timed_out": not ssh_ok and not cancel.is_set(),
                             "host": "127.0.0.1", "port": ssh_port,
                             "username": "sophyane", "forward_target": "guest:22"}
                if ssh_result is not None:
                    ssh_stage["probe"] = self._record(ssh_result, "ssh-auth-probe")
                    ssh_stage["failure_class"] = self._classify_ssh_failure(
                        ssh_result.exit_code, ssh_result.stderr or ssh_result.stdout, timed_out=ssh_result.timed_out,
                    ) if not ssh_ok else ""
                commands.append(ssh_stage)
                if ssh_ok and ssh_result is not None:
                    commands.append({"label": "guest-ssh-identity", "exit_code": 0,
                                     "timestamp": self._timestamp(), "diagnostic": ssh_result.stdout.strip()})
                if not boot_ok:
                    error = "Ubuntu guest did not reach multi-user.target"
                elif not ssh_ok:
                    error = "authenticated guest SSH did not become ready"
                cloud_ok = False
                listening = False
                if boot_ok and ssh_ok:
                    cloud_deadline = min(deadline, time.monotonic() + 600)
                    cloud_diag = "cloud-init status not yet available"
                    while time.monotonic() < cloud_deadline and not cancel.is_set():
                        result = self._ssh(ssh_port, key_file, "cloud-init status --format=json",
                                           known_hosts=known_hosts_file, cwd=workspace,
                                           cancel=cancel, timeout=15)
                        try:
                            cloud = json.loads(result.stdout)
                            cloud_diag = result.stdout[-4000:]
                            if result.exit_code == 0 and cloud.get("status") == "done":
                                cloud_ok = not cloud.get("errors")
                                break
                            if cloud.get("status") == "error" or cloud.get("errors"):
                                break
                        except (ValueError, AttributeError):
                            cloud_diag = result.stdout[-2000:] or result.stderr[-2000:] or f"exit {result.exit_code}"
                        if process.poll() is not None:
                            cloud_diag = f"QEMU exited during cloud-init check (exit {process.returncode})"
                            break
                        cancel.wait(0.5)
                    commands.append({"label": "guest-cloud-init-complete", "exit_code": 0 if cloud_ok else 1,
                                     "timestamp": self._timestamp(), "diagnostic": cloud_diag,
                                     "timed_out": not cloud_ok and not cancel.is_set()})
                    if not cloud_ok:
                        error = "guest cloud-init is incomplete or reported errors"
                    if cloud_ok:
                        stage_ok = stage_wait("guest-dependency-install-stage", "guest_dependencies", deadline)
                        dependency = None
                        if stage_ok:
                            dependency = ssh_probe(
                                "guest-dependencies-installed",
                                "/opt/sophyane-venv/bin/pip check && "
                                "/opt/sophyane-venv/bin/python -c 'import fastapi, uvicorn, psycopg, jwt, pytest; print(\"runtime imports passed\")'",
                            )
                        ok = bool(stage_ok and dependency and dependency.exit_code == 0)
                        if not ok:
                            error = "guest dependency installation failed or timed out"
                        if ok:
                            stage_ok = stage_wait("guest-migration-stage", "guest_migrations", deadline)
                            migration = None
                            if stage_ok:
                                migration = ssh_probe(
                                    "guest-database-migrations",
                                    "psql -d postgresql:///inventory -v ON_ERROR_STOP=1 -Atc "
                                    "\"SELECT to_regclass('public.inventory') IS NOT NULL\"",
                                )
                                if migration.stdout.strip() != "t":
                                    migration.exit_code = 1
                            ok = bool(stage_ok and migration and migration.exit_code == 0
                                      and migration.stdout.strip() == "t")
                            if not ok:
                                error = "guest database migration failed or timed out"
                            else:
                                commands.append({"label": "guest-dependencies-and-migration", "exit_code": 0,
                                                 "timestamp": self._timestamp(),
                                                 "diagnostic": "declared dependencies and migration stage passed"})
                        if ok:
                            listen = ssh_probe("guest-fastapi-listening", "systemctl is-active --quiet sophyane-remote-fastapi.service && ss -ltn | grep -q ':8000 '")
                            listening = listen.exit_code == 0
                            if not listening:
                                error = "FastAPI systemd service is not listening on guest port 8000"
                        else:
                            listening = False
                    else:
                        listening = False
                else:
                    listening = False
                health_ok = False
                response_status = 0
                if listening:
                    remaining = max(0.1, deadline - time.monotonic())
                    ready, diagnostic = self._wait_http(
                        f"http://127.0.0.1:{app_port}/healthz", cancel,
                        window_seconds=min(self.health_timeout, remaining),
                    )
                    health_ok = ready
                    commands.append({"label": "guest-fastapi-health-from-host", "url": f"http://127.0.0.1:{app_port}/healthz",
                                     "exit_code": 0 if ready else 1, "timestamp": self._timestamp(),
                                     "diagnostic": diagnostic})
                    if ready:
                        response_status, response_body = self.http_get(f"http://127.0.0.1:{app_port}/api/inventory", 5)
                        commands.append({"label": "guest-api-auth-enforcement-from-host", "exit_code": 0 if response_status == 401 else 1,
                                         "timestamp": self._timestamp(), "http_status": response_status,
                                         "body_sha256": hashlib.sha256(response_body).hexdigest()})
                        test_command = (
                            "sudo -n sh -c '. /mnt/sophyane-output/runner.env; "
                            "export TEST_DATABASE_URL=\"$DATABASE_URL\"; "
                            "exec runuser -u sophyane -- env APP_ENV=production "
                            "DATABASE_URL=\"$DATABASE_URL\" TEST_DATABASE_URL=\"$TEST_DATABASE_URL\" "
                            "JWT_SECRET=\"$JWT_SECRET\" PYTHONPATH=\"$SOPHYANE_PROJECT\" "
                            "/opt/sophyane-venv/bin/pytest -q \"$SOPHYANE_PROJECT/tests\"'"
                        )
                        test_result = ssh_probe("guest-saas-tests", test_command, timeout=600)
                        if test_result.exit_code:
                            error = "guest SaaS integration tests failed"
                        host_report = {
                            "schema": "sophyane.qemu-host-verification.v1",
                            "tested_project_sha256": manifest.get("source_sha256"),
                            "pytest_exit_code": test_result.exit_code,
                            "pytest_output": test_result.stdout[-48000:],
                            "checks": [row for row in commands if row.get("label") in {
                                "guest-dependencies-installed", "guest-database-migrations",
                                "guest-fastapi-listening", "guest-fastapi-health-from-host",
                                "guest-api-auth-enforcement-from-host", "guest-saas-tests",
                            }],
                        }
                        artifacts["qemu-host-verification.json"] = json.dumps(host_report, sort_keys=True, indent=2).encode()
                if ssh_ok:
                    diagnostics = ssh_probe("guest-diagnostics",
                        "systemctl status sophyane-remote-fastapi.service --no-pager; "
                        "journalctl -u sophyane-remote-fastapi.service --no-pager -n 100; "
                        "cat /mnt/sophyane-output/qemu-readiness.json /mnt/sophyane-output/qemu-execution.json 2>/dev/null || true",
                        timeout=30)
                    artifacts["qemu-guest-diagnostics.txt"] = diagnostics.stdout.encode("utf-8", errors="replace")[-128_000:]
                    execution = ssh_probe("guest-execution-report", "cat /mnt/sophyane-output/qemu-execution.json 2>/dev/null || true")
                    readiness = ssh_probe("guest-readiness-report", "cat /mnt/sophyane-output/qemu-readiness.json 2>/dev/null || true")
                    for name, raw in (("qemu-execution.json", execution.stdout), ("qemu-readiness.json", readiness.stdout)):
                        if raw.strip():
                            artifacts[name] = raw.encode()
                console = self._guest_console(log)
                process_check = next(item for item in commands if item["label"] == "qemu-process-alive")
                process_check["exit_code"] = 0 if process.poll() is None else 1
                process_check["elapsed_seconds"] = round(time.monotonic() - started, 3)
                tests_ok = any(row.get("label") == "guest-saas-tests" and row.get("exit_code") == 0
                               for row in commands)
                passed = bool(boot_ok and ssh_ok and cloud_ok and listening and health_ok
                              and response_status == 401 and tests_ok and not cancel.is_set())
                if passed:
                    error = ""
                artifacts["qemu-guest-console.log"] = console[-256_000:]
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=5)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
            if overlay.exists():
                overlay.unlink(missing_ok=True)
            for filename in ("qemu-readiness.json", "qemu-execution.json"):
                report_path = output_dir / filename
                if report_path.is_file() and filename not in artifacts:
                    try:
                        artifacts[filename] = report_path.read_bytes()[-128_000:]
                    except OSError:
                        pass
            shutil.rmtree(output_dir, ignore_errors=True)
            shutil.rmtree(key_dir, ignore_errors=True)
            readiness_labels = {
                "qemu-process-alive", "ubuntu-boot-complete", "guest-ssh-authenticated",
                    "guest-9p-mounts",
                "guest-cloud-init-complete", "guest-dependencies-installed", "guest-fastapi-listening",
                "guest-fastapi-health-from-host", "guest-database-migrations", "guest-saas-tests",
            }
            recorded = {item.get("label") for item in commands}
            for label in sorted(readiness_labels - recorded):
                if label == "guest-9p-mounts":
                    commands.append({"label": label, "exit_code": 1, "skipped": False,
                                     "timestamp": self._timestamp(),
                                     "diagnostic": "guest did not provide passing source and output 9p mount evidence"})
                    continue
                commands.append({"label": label, "exit_code": None, "skipped": True,
                                 "timestamp": self._timestamp(), "diagnostic": f"not reached: {error}"})
        return {"passed": passed, "error": error, "commands": commands, "artifacts": artifacts}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
