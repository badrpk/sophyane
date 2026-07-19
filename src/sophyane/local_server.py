"""Persistent llama.cpp server lifecycle for local GGUF mode."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse


def _state() -> dict:
    path = Path.home() / ".local" / "state" / "sophyane" / "gguf_runtime.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _port(endpoint: str) -> int:
    try:
        return int(urlparse(endpoint).port or 8766)
    except (TypeError, ValueError):
        return 8766


def _listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def _server_path(state: dict) -> Path | None:
    candidates: list[Path] = []
    for key in ("server", "llama_server", "server_path"):
        if state.get(key):
            candidates.append(Path(str(state[key])).expanduser())
    if state.get("cli"):
        cli = Path(str(state["cli"])).expanduser()
        candidates.extend([cli.with_name("llama-server"), cli.parent / "llama-server"])
    candidates.extend(
        [
            Path.home() / ".local/share/sophyane/models/llama.cpp/runtime/llama-server",
            Path.home() / "llama.cpp/build/bin/llama-server",
        ]
    )
    command = shutil.which("llama-server")
    if command:
        candidates.append(Path(command))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def ensure_server_background() -> tuple[bool, str]:
    """Start llama-server detached if local runtime state is complete.

    This function is intentionally non-blocking. The model loads while the user
    reaches the prompt; provider requests continue to probe the same endpoint.
    """
    state = _state()
    endpoint = str(state.get("endpoint") or os.environ.get("SOPHYANE_LLAMA_SERVER") or "http://127.0.0.1:8766")
    port = _port(endpoint)
    if _listening(port):
        return True, f"llama-server already listening on {port}"

    gguf = Path(str(state.get("gguf_path") or "")).expanduser()
    server = _server_path(state)
    if not gguf.is_file():
        return False, "GGUF model file is missing"
    if server is None:
        return False, "llama-server executable is missing"

    runtime_dir = Path.home() / ".local" / "state" / "sophyane"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    log_path = runtime_dir / "llama-server.log"
    pid_path = runtime_dir / "llama-server.pid"

    command = [
        str(server), "-m", str(gguf), "--host", "127.0.0.1", "--port", str(port),
        "-c", str(int(state.get("context") or 2048)), "-ngl", str(int(state.get("gpu_layers") or 0)),
    ]
    try:
        log = log_path.open("ab", buffering=0)
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
    pid_path.write_text(str(process.pid), encoding="utf-8")
    return True, f"starting llama-server pid {process.pid} on {port}"


def wait_until_ready(timeout: float = 45.0) -> bool:
    state = _state()
    endpoint = str(state.get("endpoint") or os.environ.get("SOPHYANE_LLAMA_SERVER") or "http://127.0.0.1:8766")
    port = _port(endpoint)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _listening(port):
            return True
        time.sleep(0.5)
    return False
