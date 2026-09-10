"""Transient Mode-3 local-model profiles.

The provider identity remains ``local_gguf``.  This module only selects the
physical local runtime used by an explicit Mode-3 session.

Qwen keeps Sophyane's existing gguf_runtime.json / local_server ownership.
Spark owns an independent server on port 8767 so it cannot overwrite or
conflict with Qwen's persistent runtime state.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


STATE_DIR = Path.home() / ".local" / "state" / "sophyane"
QWEN_STATE_FILE = STATE_DIR / "gguf_runtime.json"

SPARK_ENDPOINT = os.environ.get(
    "SOPHYANE_SPARK_LLAMA_SERVER",
    "http://127.0.0.1:8767",
).rstrip("/")

SPARK_MODEL = Path(
    os.environ.get(
        "SOPHYANE_SPARK_GGUF_PATH",
        (
            Path.home()
            / ".local/share/sophyane/models/spark-x2.5-4b"
            / "Spark-X2.5-4B-Q4_K_M.gguf"
        ),
    )
).expanduser()

SPARK_SERVER = Path(
    os.environ.get(
        "SOPHYANE_SPARK_LLAMA_SERVER_BIN",
        (
            Path.home()
            / "llama.cpp-spark/build-termux-static/bin/llama-server"
        ),
    )
).expanduser()

SPARK_CONTEXT = max(
    512,
    int(
        os.environ.get(
            "SOPHYANE_SPARK_CONTEXT",
            "4096",
        )
    ),
)

SPARK_THREADS = max(
    1,
    int(
        os.environ.get(
            "SOPHYANE_SPARK_THREADS",
            "6",
        )
    ),
)

SPARK_PID_FILE = STATE_DIR / "spark-llama-server.pid"
SPARK_LOG_FILE = STATE_DIR / "spark-llama-server.log"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(
                encoding="utf-8",
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ):
        return {}

    return value if isinstance(value, dict) else {}


def qwen_profile(
    fallback_model: str = "",
) -> dict[str, Any]:
    state = _read_json(
        QWEN_STATE_FILE
    )

    return {
        "profile": "qwen",
        "model": str(
            fallback_model
            or state.get("model")
            or "qwen2.5-1.5b-instruct-q4_k_m"
        ),
        "endpoint": str(
            state.get("endpoint")
            or "http://127.0.0.1:8766"
        ).rstrip("/"),
        "gguf_path": str(
            state.get("gguf_path")
            or ""
        ),
        "server": str(
            state.get("server")
            or ""
        ),
        "context": max(
            512,
            int(
                state.get("context")
                or 8192
            ),
        ),
    }


def spark_profile() -> dict[str, Any]:
    return {
        "profile": "spark",
        "model": "Spark-X2.5-4B-Q4_K_M",
        "endpoint": SPARK_ENDPOINT,
        "gguf_path": str(
            SPARK_MODEL
        ),
        "server": str(
            SPARK_SERVER
        ),
        "context": SPARK_CONTEXT,
    }


def spark_profile_available() -> bool:
    return (
        SPARK_MODEL.is_file()
        and SPARK_SERVER.is_file()
        and os.access(
            SPARK_SERVER,
            os.X_OK,
        )
    )


def selected_profile() -> str:
    value = str(
        os.environ.get(
            "SOPHYANE_LOCAL_PROFILE"
        )
        or "qwen"
    ).strip().lower()

    if value not in {
        "qwen",
        "spark",
        "compare",
    }:
        return "qwen"

    return value


def configure_session_profile(
    profile: str,
    *,
    qwen_model: str = "",
) -> dict[str, Any]:
    """Apply transient Mode-3 model selection to this process only."""

    normalized = str(
        profile
        or "qwen"
    ).strip().lower()

    if normalized not in {
        "qwen",
        "spark",
        "compare",
    }:
        normalized = "qwen"

    qwen = qwen_profile(
        qwen_model
    )

    if normalized == "spark":
        if not spark_profile_available():
            raise RuntimeError(
                "Spark-X2.5-4B local runtime is unavailable"
            )

        selected = spark_profile()

    elif normalized == "compare":
        if not spark_profile_available():
            raise RuntimeError(
                "Spark-X2.5-4B local runtime is unavailable"
            )

        selected = {
            "profile": "compare",
            "model": (
                "qwen2.5-1.5b-vs-spark-x2.5-4b"
            ),
            # The comparison provider owns both endpoints directly.
            # Keep Qwen as the compatibility/default endpoint.
            "endpoint": qwen["endpoint"],
            "context": min(
                int(
                    qwen["context"]
                ),
                SPARK_CONTEXT,
            ),
        }

    else:
        selected = qwen

    os.environ[
        "SOPHYANE_LOCAL_PROFILE"
    ] = normalized

    os.environ[
        "SOPHYANE_SESSION_MODEL"
    ] = str(
        selected["model"]
    )

    os.environ[
        "SOPHYANE_LLAMA_SERVER"
    ] = str(
        selected["endpoint"]
    )

    os.environ[
        "SOPHYANE_LLAMA_CONTEXT"
    ] = str(
        selected.get("context")
        or 4096
    )

    return selected


def _port(
    endpoint: str,
) -> int:
    from urllib.parse import urlparse

    parsed = urlparse(
        endpoint
    )

    return int(
        parsed.port
        or 8767
    )


def _listening(
    endpoint: str,
) -> bool:
    try:
        with socket.create_connection(
            (
                "127.0.0.1",
                _port(
                    endpoint
                ),
            ),
            timeout=0.3,
        ):
            return True

    except OSError:
        return False


def _health(
    endpoint: str,
    *,
    timeout: float = 1.0,
) -> bool:
    try:
        with urllib.request.urlopen(
            endpoint.rstrip("/")
            + "/health",
            timeout=timeout,
        ) as response:
            return (
                200
                <= int(
                    response.status
                )
                < 300
            )

    except (
        OSError,
        urllib.error.URLError,
    ):
        return False


def ensure_spark_server() -> tuple[
    bool,
    str,
]:
    """Ensure Spark's independent llama-server is inference-ready.

    This function never terminates an unknown process and never mutates
    Sophyane's Qwen gguf_runtime.json ownership state.
    """

    if not spark_profile_available():
        return (
            False,
            "Spark runtime files are missing",
        )

    if _health(
        SPARK_ENDPOINT
    ):
        return (
            True,
            "Spark llama-server is listening on 8767",
        )

    if _listening(
        SPARK_ENDPOINT
    ):
        return (
            False,
            "port 8767 is occupied but Spark health check failed",
        )

    STATE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    command = [
        str(
            SPARK_SERVER
        ),
        "-m",
        str(
            SPARK_MODEL
        ),
        "--host",
        "127.0.0.1",
        "--port",
        str(
            _port(
                SPARK_ENDPOINT
            )
        ),
        "--parallel",
        "1",
        "-c",
        str(
            SPARK_CONTEXT
        ),
        "-t",
        str(
            SPARK_THREADS
        ),
        "--jinja",
    ]

    with SPARK_LOG_FILE.open(
        "ab",
        buffering=0,
    ) as log:
        log.write(
            (
                "\n=== Sophyane Spark start "
                + time.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                + " ===\nCOMMAND: "
                + " ".join(
                    command
                )
                + "\n"
            ).encode()
        )

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
            return (
                False,
                "could not start Spark llama-server: "
                + str(
                    error
                ),
            )

    SPARK_PID_FILE.write_text(
        str(
            process.pid
        )
        + "\n",
        encoding="utf-8",
    )

    # Loading a 4B model on Android may take several seconds.
    for _ in range(
        160
    ):
        if _health(
            SPARK_ENDPOINT,
            timeout=0.5,
        ):
            return (
                True,
                (
                    "Spark llama-server ready on 8767 "
                    f"(pid {process.pid})"
                ),
            )

        code = process.poll()

        if code is not None:
            try:
                tail = (
                    SPARK_LOG_FILE
                    .read_text(
                        encoding="utf-8",
                        errors="replace",
                    )[-1800:]
                )
            except OSError:
                tail = ""

            return (
                False,
                (
                    "Spark llama-server exited with code "
                    f"{code}. {tail}"
                ),
            )

        time.sleep(
            0.25
        )

    return (
        True,
        (
            "Spark llama-server is still loading "
            f"on 8767 (pid {process.pid})"
        ),
    )


def ensure_profile_servers(
    profile: str | None = None,
) -> tuple[
    bool,
    str,
]:
    """Ensure server ownership appropriate for the selected Mode-3 profile."""

    active = (
        str(
            profile
            or selected_profile()
        )
        .strip()
        .lower()
    )

    messages: list[str] = []

    if active in {
        "qwen",
        "compare",
    }:
        from sophyane.local_server import (
            ensure_server_background,
        )

        ok, message = (
            ensure_server_background()
        )

        messages.append(
            "Qwen: "
            + message
        )

        if not ok:
            return (
                False,
                "; ".join(
                    messages
                ),
            )

    if active in {
        "spark",
        "compare",
    }:
        ok, message = (
            ensure_spark_server()
        )

        messages.append(
            "Spark: "
            + message
        )

        if not ok:
            return (
                False,
                "; ".join(
                    messages
                ),
            )

    return (
        True,
        "; ".join(
            messages
        ),
    )
