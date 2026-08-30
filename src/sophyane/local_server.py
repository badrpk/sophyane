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
LOCK_FILE = RUNTIME_DIR / "llama-server.starting"

# SOPHYANE_LLAMA_SINGLE_OWNER_V1


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



def _process_cmdline(pid: int) -> str:
    """Read a process command line without trusting a reused PID."""
    if pid <= 0:
        return ""

    try:
        return (
            Path(f"/proc/{pid}/cmdline")
            .read_bytes()
            .replace(b"\0", b" ")
            .decode(
                "utf-8",
                errors="replace",
            )
        )
    except OSError:
        return ""


def _expected_gguf(
    state: dict | None = None,
) -> Path | None:
    value = str(
        (state or _state()).get(
            "gguf_path"
        )
        or ""
    ).strip()

    if not value:
        return None

    return Path(value).expanduser()


def _discover_matching_local_server_pid(
    port: int,
    state: dict[str, object],
) -> int | None:
    """Find one live local llama-server that exactly matches configuration.

    Discovery is intentionally conservative.  A process is adoptable only
    when its command line identifies llama-server, the configured port, and
    the configured GGUF path.  Ambiguous matches are never adopted.
    """
    expected_model = str(
        state.get("gguf_path", "")
        or ""
    ).strip()

    if not expected_model:
        return None

    proc_root = Path("/proc")

    if not proc_root.is_dir():
        return None

    matches: list[int] = []

    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue

        pid = int(entry.name)

        try:
            raw = (
                entry
                / "cmdline"
            ).read_bytes()
        except OSError:
            continue

        if not raw:
            continue

        argv = [
            token.decode(
                "utf-8",
                errors="replace",
            )
            for token in raw.split(b"\0")
            if token
        ]

        if not argv:
            continue

        rendered = "\n".join(argv)

        if "llama-server" not in rendered:
            continue

        if expected_model not in argv:
            continue

        port_match = False

        for index, token in enumerate(argv):
            if token in {
                "--port",
                "-p",
            }:
                if (
                    index + 1 < len(argv)
                    and argv[index + 1]
                    == str(port)
                ):
                    port_match = True
                    break

            if token == f"--port={port}":
                port_match = True
                break

        if not port_match:
            continue

        matches.append(pid)

    if len(matches) != 1:
        return None

    return matches[0]


def _reconcile_server_pid(
    port: int,
    state: dict[str, object],
) -> int | None:
    """Return the verified owner PID, adopting a unique exact live match."""
    recorded_pid = _read_pid()

    if (
        recorded_pid is not None
        and _pid_matches_expected_server(
            recorded_pid,
            state,
            port,
        )
    ):
        return recorded_pid

    discovered_pid = (
        _discover_matching_local_server_pid(
            port,
            state,
        )
    )

    if discovered_pid is None:
        return None

    # Re-check immediately before persisting ownership.
    if not _pid_matches_expected_server(
        discovered_pid,
        state,
        port,
    ):
        return None

    _write_pid(discovered_pid)

    return discovered_pid


def _pid_matches_expected_server(
    pid: int,
    state: dict | None = None,
    port: int | None = None,
) -> bool:
    """Prove PID ownership before reuse or termination."""
    command = _process_cmdline(
        pid
    )

    if "llama-server" not in command:
        return False

    gguf = _expected_gguf(
        state
    )

    if gguf is None:
        return False

    if not (
        str(gguf) in command
        or gguf.name in command
    ):
        return False

    if port is None:
        return True

    tokens = command.split()

    for index, token in enumerate(tokens):
        if token in {
            "--port",
            "-p",
        }:
            if (
                index + 1 < len(tokens)
                and tokens[index + 1]
                == str(port)
            ):
                return True

        if token == f"--port={port}":
            return True

    return False


def _models_match_expected(
    port: int,
    state: dict | None = None,
) -> bool:
    """Require /v1/models to identify the configured GGUF."""
    import urllib.error
    import urllib.request

    gguf = _expected_gguf(
        state
    )

    if gguf is None:
        return False

    expected = {
        str(gguf).casefold(),
        gguf.name.casefold(),
        gguf.stem.casefold(),
    }

    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/v1/models",
            timeout=1.5,
        ) as response:

            if response.status != 200:
                return False

            payload = json.loads(
                response.read().decode(
                    "utf-8",
                    errors="replace",
                )
            )

    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        urllib.error.HTTPError,
        urllib.error.URLError,
    ):
        return False

    data = (
        payload.get("data")
        if isinstance(
            payload,
            dict,
        )
        else None
    )

    if not isinstance(
        data,
        list,
    ):
        return False

    for entry in data:

        if not isinstance(
            entry,
            dict,
        ):
            continue

        model_id = str(
            entry.get("id")
            or ""
        ).strip()

        if not model_id:
            continue

        observed = {
            model_id.casefold(),
            Path(model_id).name.casefold(),
            Path(model_id).stem.casefold(),
        }

        if expected & observed:
            return True

    return False


def _boot_id() -> str:
    try:
        return (
            Path(
                "/proc/sys/kernel/random/boot_id"
            )
            .read_text(
                encoding="utf-8"
            )
            .strip()
        )
    except OSError:
        return ""


def _read_start_lock() -> tuple[int, str]:
    try:
        text = LOCK_FILE.read_text(
            encoding="utf-8"
        ).strip()
    except OSError:
        return 0, ""

    try:
        value = json.loads(
            text
        )

        if isinstance(
            value,
            dict,
        ):
            return (
                int(
                    value.get(
                        "pid"
                    )
                    or 0
                ),
                str(
                    value.get(
                        "boot_id"
                    )
                    or ""
                ),
            )

    except (
        ValueError,
        TypeError,
        json.JSONDecodeError,
    ):
        pass

    try:
        return int(text), ""
    except ValueError:
        return 0, ""


def _acquire_start_lock() -> int | None:
    """Acquire startup ownership; recover only provably stale locks."""
    RUNTIME_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    for _ in range(2):

        try:
            fd = os.open(
                LOCK_FILE,
                os.O_CREAT
                | os.O_EXCL
                | os.O_WRONLY,
                0o600,
            )

        except FileExistsError:

            owner_pid, owner_boot = (
                _read_start_lock()
            )

            current_boot = (
                _boot_id()
            )

            same_boot = (
                not owner_boot
                or not current_boot
                or owner_boot
                == current_boot
            )

            if (
                same_boot
                and _pid_alive(
                    owner_pid
                )
            ):
                return None

            try:
                LOCK_FILE.unlink()
            except OSError:
                return None

            continue

        payload = json.dumps(
            {
                "pid":
                    os.getpid(),
                "boot_id":
                    _boot_id(),
                "created":
                    time.time(),
            },
            sort_keys=True,
        ).encode(
            "utf-8"
        )

        os.write(
            fd,
            payload,
        )

        return fd

    return None

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


def _write_pid(
    pid: int,
) -> None:
    """Persist verified llama-server ownership."""
    PID_FILE.write_text(
        str(pid),
        encoding="utf-8",
    )


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

    configured = str(
        os.environ.get(
            "SOPHYANE_LLAMA_SERVER_BIN",
            "",
        )
        or ""
    ).strip()

    if configured:
        explicit = Path(
            configured
        ).expanduser()

        if (
            explicit.is_file()
            and os.access(
                explicit,
                os.X_OK,
            )
        ):
            return explicit

        # Explicit configuration is authoritative.
        # Fail closed instead of silently selecting
        # a different executable.
        return None
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
    """Return ready, loading, stalled, foreign, stopped, or failed."""
    state = _state()
    port = _configured_port()
    pid = _reconcile_server_pid(
        port,
        state,
    )

    if _listening(
        port
    ):

        if _models_match_expected(
            port,
            state,
        ):
            return (
                "ready",
                f"configured llama-server "
                f"is listening on {port}",
            )

        if (
            _pid_alive(
                pid
            )
            and _pid_matches_expected_server(
                pid,
                state,
                port,
            )
        ):
            age = _startup_age()

            if age >= STALL_SECONDS:
                return (
                    "stalled",
                    f"configured llama-server "
                    f"process {pid} is not "
                    f"inference-ready after "
                    f"{int(age)}s. "
                    f"Log: {_log_tail()}",
                )

            return (
                "loading",
                f"configured llama-server "
                f"process {pid} is loading "
                f"on {port} "
                f"({int(age)}s)",
            )

        return (
            "foreign",
            f"port {port} is occupied by "
            f"an unexpected or unverifiable "
            f"process; refusing reuse or kill",
        )

    if _pid_alive(
        pid
    ):

        if not _pid_matches_expected_server(
            pid,
            state,
            port,
        ):
            return (
                "foreign",
                f"recorded PID {pid} is not "
                f"the configured llama-server; "
                f"refusing ownership",
            )

        age = _startup_age()

        if age >= STALL_SECONDS:
            return (
                "stalled",
                f"llama-server process {pid} "
                f"has not opened {port} "
                f"after {int(age)}s. "
                f"Log: {_log_tail()}",
            )

        return (
            "loading",
            f"llama-server process {pid} "
            f"is loading on {port} "
            f"({int(age)}s)",
        )

    if pid:
        return (
            "failed",
            f"llama-server process {pid} "
            f"exited before listening. "
            f"Log: {_log_tail()}",
        )

    return (
        "stopped",
        f"llama-server is not "
        f"running on {port}",
    )



def _launch(state: dict, port: int, *, minimal: bool = False) -> tuple[bool, str]:
    gguf = Path(str(state.get("gguf_path") or "")).expanduser()
    server = _server_path(state)
    if not gguf.is_file():
        return False, f"GGUF model file is missing: {gguf}"
    if server is None:
        return False, "llama-server executable is missing"

    command = [
        str(server),
        "-m",
        str(gguf),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),

        # SOPHYANE_LLAMA_MOBILE_SINGLE_SLOT_V1
        #
        # Sophyane's local provider performs one bounded generation at a
        # time. llama-server's automatic four-slot configuration adds
        # unnecessary KV/cache and resident-memory pressure on Android.
        #
        # Keep this configurable for larger machines, while making one slot
        # the conservative local/mobile default.
        "--parallel",
        str(
            max(
                1,
                int(
                    state.get(
                        "parallel",
                    )
                    or os.environ.get(
                        "SOPHYANE_LLAMA_PARALLEL",
                        "1",
                    )
                ),
            )
        ),
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
    """Own exactly one persistent llama-server process."""
    state = _state()
    port = _configured_port()

    status, message = (
        server_status()
    )

    if status in {
        "ready",
        "loading",
    }:
        return True, message

    if status == "foreign":
        return False, message

    if status == "stalled":

        old_pid = _read_pid()

        if not _pid_matches_expected_server(
            old_pid,
            state,
            port,
        ):
            return (
                False,
                f"refusing to terminate "
                f"unverified PID {old_pid}",
            )

        _terminate_process_group(
            old_pid
        )

        _clear_runtime_state()

    lock_fd = (
        _acquire_start_lock()
    )

    if lock_fd is None:
        return (
            True,
            f"llama-server startup "
            f"already in progress "
            f"on {port}",
        )

    try:

        # Another caller may have completed
        # startup while this caller was waiting.
        status, message = (
            server_status()
        )

        if status in {
            "ready",
            "loading",
        }:
            return True, message

        if status == "foreign":
            return False, message

        return _launch(
            state,
            port,
            minimal=(
                status == "stalled"
            ),
        )

    finally:

        try:
            os.close(
                lock_fd
            )
        finally:
            try:
                LOCK_FILE.unlink()
            except OSError:
                pass



def wait_until_ready(timeout: float = 20.0) -> bool:
    """Wait until llama-server is genuinely ready for inference.

    SOPHYANE_LLAMA_TRUE_HTTP_READINESS_V1

    A listening TCP port is insufficient: llama-server may expose the
    socket while the model is still loading and /health returns HTTP 503.
    Readiness therefore requires an HTTP 200 response whose health payload
    reports status=ok.
    """
    import json
    import urllib.error
    import urllib.request

    deadline = time.monotonic() + max(
        0.0,
        float(timeout),
    )

    port = _configured_port()

    health_url = (
        f"http://127.0.0.1:{port}/health"
    )

    while time.monotonic() < deadline:
        try:
            request = urllib.request.Request(
                health_url,
                headers={
                    "Accept":
                        "application/json",
                },
            )

            with urllib.request.urlopen(
                request,
                timeout=2.0,
            ) as response:
                if response.status != 200:
                    time.sleep(0.25)
                    continue

                body = response.read().decode(
                    "utf-8",
                    errors="replace",
                )

                try:
                    payload = json.loads(
                        body
                    )
                except json.JSONDecodeError:
                    payload = {}

                if (
                    isinstance(
                        payload,
                        dict,
                    )
                    and str(
                        payload.get(
                            "status",
                            "",
                        )
                    ).casefold()
                    == "ok"
                ):
                    return True

        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            OSError,
        ):
            pass

        time.sleep(
            0.25
        )

    return False

def failure_detail() -> str:
    status, message = server_status()
    return message if status != "ready" else ""


def wait_until_idle(
    timeout: float = 20.0,
    *,
    poll_interval: float = 0.2,
) -> bool:
    """Wait until every llama-server inference slot is idle.

    SOPHYANE_LOCAL_SERVER_SLOT_QUIESCENCE_V1

    HTTP cancellation is asynchronous inside llama-server. A client timeout
    may therefore occur before the server has fully released the associated
    inference slot.

    This helper proves actual slot quiescence rather than assuming that a
    cancelled HTTP request immediately frees model execution state.
    """
    import json
    import urllib.error
    import urllib.request

    deadline = (
        time.monotonic()
        + max(
            0.0,
            float(
                timeout
            ),
        )
    )

    while True:
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:"
                + str(
                    _configured_port()
                )
                + "/slots",
                timeout=min(
                    2.0,
                    max(
                        0.25,
                        deadline
                        - time.monotonic(),
                    ),
                ),
            ) as response:
                slots = json.loads(
                    response.read().decode(
                        "utf-8"
                    )
                )

            if (
                isinstance(
                    slots,
                    list,
                )
                and not any(
                    bool(
                        slot.get(
                            "is_processing"
                        )
                    )
                    for slot in slots
                    if isinstance(
                        slot,
                        dict,
                    )
                )
            ):
                return True

        except (
            OSError,
            ValueError,
            urllib.error.URLError,
            json.JSONDecodeError,
        ):
            pass

        if (
            time.monotonic()
            >= deadline
        ):
            return False

        time.sleep(
            max(
                0.05,
                float(
                    poll_interval
                ),
            )
        )
