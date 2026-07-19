"""Persistent llama.cpp server lifecycle for local GGUF mode."""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

RUNTIME_DIR = Path.home() / ".local" / "state" / "sophyane"
STATE_FILE = RUNTIME_DIR / "gguf_runtime.json"
LOG_FILE = RUNTIME_DIR / "llama-server.log"
PID_FILE = RUNTIME_DIR / "llama-server.pid"
START_FILE = RUNTIME_DIR / "llama-server.started"
STALL_SECONDS = 90.0


def _state() -> dict:
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _port(endpoint: str) -> int:
    try:
        return int(urlparse(endpoint).port or 8766)
    except (TypeError, ValueError):
        return 8766


def _configured_port() -> int:
    state = _state()
    endpoint = str(
        state.get("endpoint")
        or os.environ.get("SOPHYANE_LLAMA_SERVER")
        or "http://127.0.0.1:8766"
    )
    return _port(endpoint)


def _listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_pid() -> int:
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def _started_at() -> float:
    try:
        return float(START_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0.0


def _startup_age() -> float:
    started = _started_at()
    return max(0.0, time.time() - started) if started else 0.0


def _clear_runtime_state() -> None:
    for path in (PID_FILE, START_FILE):
        try:
            path.unlink()
        except OSError:
            pass


def _terminate_process_group(pid: int) -> None:
    if not _pid_alive(pid):
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return
        time.sleep(0.1)
    try:
        os.killpg(pid, signal.SIGKILL)
    except OSError:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def _log_tail(limit: int = 1600) -> str:
    try:
        text = LOG_FILE.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "no llama-server log was written"
    text = text.strip()
    return text[-limit:] if text else "llama-server log is empty"


def _server_path(state: dict) -> Path | None:
    candidates: list[Path] = []
    for key in ("server", "llama_server", "server_path"):
        if state.get(key):
            candidates.append(Path(str(state[key])).expanduser())
    if state.get("cli"):
        cli = Path(str(state["cli"])).expanduser()
        candidates.extend([cli.with_name("llama-server"), cli.parent / "llama-server"])
    candidates.extend([
        Path.home() / ".local/share/sophyane/models/llama.cpp/runtime/llama-server",
        Path.home() / "llama.cpp/build/bin/llama-server",
    ])
    command = shutil.which("llama-server")
    if command:
        candidates.append(Path(command))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def server_status() -> tuple[str, str]:
    """Return ready, loading, stalled, stopped, or failed."""
    port = _configured_port()
    if _listening(port):
        return "ready", f"llama-server is listening on {port}"
    pid = _read_pid()
    if _pid_alive(pid):
        age = _startup_age()
        if age >= STALL_SECONDS:
            return (
                "stalled",
                f"llama-server process {pid} has not opened {port} after {int(age)}s. "
                f"Log: {_log_tail()}",
            )
        return "loading", f"llama-server process {pid} is loading on {port} ({int(age)}s)"
    if pid:
        return "failed", f"llama-server process {pid} exited before listening. Log: {_log_tail()}"
    return "stopped", f"llama-server is not running on {port}"


def _launch(state: dict, port: int, *, minimal: bool = False) -> tuple[bool, str]:
    gguf = Path(str(state.get("gguf_path") or "")).expanduser()
    server = _server_path(state)
    if not gguf.is_file():
        return False, f"GGUF model file is missing: {gguf}"
    if server is None:
        return False, "llama-server executable is missing"

    command = [
        str(server), "-m", str(gguf),
        "--host", "127.0.0.1", "--port", str(port),
    ]
    if not minimal:
        command += ["-c", str(int(state.get("context") or 2048))]
        gpu_layers = int(state.get("gpu_layers") or 0)
        if gpu_layers:
            command += ["-ngl", str(gpu_layers)]

    _clear_runtime_state()
    with LOG_FILE.open("ab", buffering=0) as log:
        mode = "minimal retry" if minimal else "normal"
        log.write(
            f"\n=== Sophyane llama-server start {time.strftime('%Y-%m-%d %H:%M:%S')} ({mode}) ===\n".encode()
        )
        log.write(("COMMAND: " + " ".join(command) + "\n").encode())
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as error:
            return False, f"could not start llama-server: {error}"

    PID_FILE.write_text(str(process.pid), encoding="utf-8")
    START_FILE.write_text(str(time.time()), encoding="utf-8")
    for _ in range(12):
        time.sleep(0.25)
        if _listening(port):
            return True, f"llama-server ready on {port} (pid {process.pid})"
        code = process.poll()
        if code is not None:
            _clear_runtime_state()
            return False, (
                f"llama-server exited with code {code} before listening on {port}. "
                f"Log: {_log_tail()}"
            )
    return True, f"llama-server process {process.pid} is loading on {port}"


def ensure_server_background() -> tuple[bool, str]:
    """Start one detached llama-server and recover one stalled startup."""
    state = _state()
    port = _configured_port()
    status, message = server_status()
    if status in {"ready", "loading"}:
        return True, message
    if status == "stalled":
        old_pid = _read_pid()
        _terminate_process_group(old_pid)
        _clear_runtime_state()

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = RUNTIME_DIR / "llama-server.starting"
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return True, f"llama-server startup already in progress on {port}"

    try:
        os.write(lock_fd, str(os.getpid()).encode())
        ok, launch_message = _launch(state, port, minimal=(status == "stalled"))
        if ok:
            return True, launch_message
        return False, launch_message
    finally:
        os.close(lock_fd)
        try:
            lock_path.unlink()
        except OSError:
            pass


def wait_until_ready(timeout: float = 20.0) -> bool:
    port = _configured_port()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _listening(port):
            return True
        status, _ = server_status()
        if status in {"failed", "stalled", "stopped"}:
            return False
        time.sleep(0.5)
    return False


def failure_detail() -> str:
    status, message = server_status()
    return message if status != "ready" else ""
