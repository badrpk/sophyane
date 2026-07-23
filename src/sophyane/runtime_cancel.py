"""Generation-scoped cooperative cancellation for provider work."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass(eq=False)
class CancellationToken:
    """Cancellation state belonging to one provider generation."""

    event: threading.Event = field(default_factory=threading.Event)
    processes: set[subprocess.Popen[Any]] = field(default_factory=set)


_LOCK = threading.RLock()
_LOCAL = threading.local()
_TOKENS: set[CancellationToken] = set()
_LEGACY_TOKEN = CancellationToken()
_TOKENS.add(_LEGACY_TOKEN)


def new_generation() -> CancellationToken:
    """Create and register a fresh cancellation token."""

    token = CancellationToken()

    with _LOCK:
        _TOKENS.add(token)

    return token


def bind_generation(token: CancellationToken) -> None:
    """Bind the calling thread to a provider generation."""

    _LOCAL.token = token


def current_generation() -> CancellationToken:
    """Return the token belonging to the current worker thread."""

    token = getattr(_LOCAL, "token", None)

    if isinstance(token, CancellationToken):
        return token

    return _LEGACY_TOKEN


def release_generation(token: CancellationToken) -> None:
    """Forget a completed token after its subprocesses have exited."""

    with _LOCK:
        if not token.processes and token is not _LEGACY_TOKEN:
            _TOKENS.discard(token)

    if getattr(_LOCAL, "token", None) is token:
        try:
            delattr(_LOCAL, "token")
        except AttributeError:
            pass


def reset_cancel() -> None:
    """Backward-compatible reset for only the current generation."""

    current_generation().event.clear()


def cancelled(token: CancellationToken | None = None) -> bool:
    """Return whether the selected/current generation was cancelled."""

    selected = token or current_generation()
    return selected.event.is_set()


def register(
    process: subprocess.Popen[Any],
    token: CancellationToken | None = None,
) -> None:
    """Register a subprocess under the current generation."""

    selected = token or current_generation()

    with _LOCK:
        _TOKENS.add(selected)
        selected.processes.add(process)


def unregister(
    process: subprocess.Popen[Any],
    token: CancellationToken | None = None,
) -> None:
    """Remove a subprocess from its generation."""

    selected = token or current_generation()

    with _LOCK:
        selected.processes.discard(process)

        if (
            selected is not _LEGACY_TOKEN
            and not selected.processes
            and selected.event.is_set()
        ):
            _TOKENS.discard(selected)


def _terminate_processes(processes: list[subprocess.Popen[Any]]) -> None:
    for process in processes:
        if process.poll() is not None:
            continue

        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
        except (ProcessLookupError, PermissionError, OSError):
            try:
                process.terminate()
            except OSError:
                pass

    for process in processes:
        try:
            process.wait(timeout=1.5)
        except (subprocess.TimeoutExpired, OSError):
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except (ProcessLookupError, PermissionError, OSError):
                pass


def cancel_generation(token: CancellationToken) -> None:
    """Cancel only one provider generation."""

    token.event.set()

    with _LOCK:
        processes = list(token.processes)

    _terminate_processes(processes)

    with _LOCK:
        token.processes.clear()


def cancel_all() -> None:
    """Cancel every known generation, such as during process shutdown."""

    with _LOCK:
        tokens = list(_TOKENS)

    for token in tokens:
        token.event.set()

    processes: list[subprocess.Popen[Any]] = []

    with _LOCK:
        for token in tokens:
            processes.extend(token.processes)

    # Avoid terminating the same process twice.
    unique_processes = list(dict.fromkeys(processes))
    _terminate_processes(unique_processes)

    with _LOCK:
        for token in tokens:
            token.processes.clear()
