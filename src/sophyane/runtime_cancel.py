"""Cooperative cancellation for local provider subprocesses."""
from __future__ import annotations

import os
import signal
import subprocess
import threading
from typing import Any

_LOCK = threading.RLock()
_ACTIVE: set[subprocess.Popen[Any]] = set()
_CANCELLED = threading.Event()


def reset_cancel() -> None:
    _CANCELLED.clear()


def cancelled() -> bool:
    return _CANCELLED.is_set()


def register(process: subprocess.Popen[Any]) -> None:
    with _LOCK:
        _ACTIVE.add(process)


def unregister(process: subprocess.Popen[Any]) -> None:
    with _LOCK:
        _ACTIVE.discard(process)


def cancel_all() -> None:
    _CANCELLED.set()
    with _LOCK:
        processes = list(_ACTIVE)
    for process in processes:
        if process.poll() is not None:
            unregister(process)
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
        finally:
            unregister(process)
