"""Validated one-shot protocol shared by the host runner and guest service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


MAX_TASK_ID = 256
MAX_ARGUMENTS = 64
MAX_ARGUMENT_LENGTH = 4096
MAX_OUTPUT_LENGTH = 65536
ALLOWED_EXECUTABLES = frozenset({"python", "python3", "pytest", "/usr/bin/python3", "/usr/bin/pytest"})
ALLOWED_CWD = "/mnt/sophyane-input/candidate"
RESULT_KEYS = frozenset({"schema_version", "task_id", "status", "exit_code", "stdout", "stderr"})


class GuestProtocolError(ValueError):
    """Guest input or output violates the fixed protocol."""


@dataclass(frozen=True)
class GuestManifest:
    task_id: str
    command: tuple[str, ...]
    cwd: str
    schema_version: int = 1


@dataclass(frozen=True)
class GuestResult:
    task_id: str
    status: str
    exit_code: int
    stdout: str
    stderr: str
    schema_version: int = 1


def _string(value: Any, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        prefix = "output " if name in {"stdout", "stderr"} else ""
        raise GuestProtocolError(f"{prefix}{name} is invalid or too large")
    return value


def validate_manifest(payload: Any) -> GuestManifest:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise GuestProtocolError("manifest schema_version must be 1")
    task_id = _string(payload.get("task_id"), "task_id", MAX_TASK_ID)
    command = payload.get("command")
    if not isinstance(command, list) or not 2 <= len(command) <= MAX_ARGUMENTS:
        raise GuestProtocolError("command must be a non-empty argv list")
    if any(not isinstance(item, str) or not item or len(item) > MAX_ARGUMENT_LENGTH for item in command):
        raise GuestProtocolError("command contains an invalid argument")
    executable = command[0]
    if executable not in ALLOWED_EXECUTABLES:
        raise GuestProtocolError("command executable is not allowlisted")
    if any(marker in item for item in command for marker in (";", "|", "&", "$", "`", "<", ">")):
        raise GuestProtocolError("shell syntax is forbidden")
    cwd = _string(payload.get("cwd"), "cwd", MAX_ARGUMENT_LENGTH)
    if cwd != ALLOWED_CWD and not cwd.startswith(ALLOWED_CWD + "/"):
        raise GuestProtocolError("cwd must remain inside candidate root")
    if ".." in cwd.split("/"):
        raise GuestProtocolError("cwd traversal is forbidden")
    return GuestManifest(task_id, tuple(command), cwd)


def validate_result(payload: Any) -> GuestResult:
    if not isinstance(payload, dict) or set(payload) != RESULT_KEYS:
        unknown = set(payload) - RESULT_KEYS if isinstance(payload, dict) else set()
        detail = f": {sorted(unknown)}" if unknown else ""
        raise GuestProtocolError(f"result schema contains unexpected or missing fields{detail}")
    if payload.get("schema_version") != 1:
        raise GuestProtocolError("result schema_version must be 1")
    task_id = _string(payload.get("task_id"), "task_id", MAX_TASK_ID)
    status = payload.get("status")
    if status not in {"passed", "failed"}:
        raise GuestProtocolError("result status is invalid")
    exit_code = payload.get("exit_code")
    if not isinstance(exit_code, int) or not -255 <= exit_code <= 255:
        raise GuestProtocolError("result exit_code is invalid")
    stdout = _string(payload.get("stdout") or "", "stdout", MAX_OUTPUT_LENGTH) if payload.get("stdout") else ""
    stderr = _string(payload.get("stderr") or "", "stderr", MAX_OUTPUT_LENGTH) if payload.get("stderr") else ""
    return GuestResult(task_id, status, exit_code, stdout, stderr)
