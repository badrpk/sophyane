"""Safe execution of Sophyane-generated task programs."""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any

from sophyane.task_compiler import (
    CompiledTask,
)


STATE_ROOT = (
    Path.home()
    / ".local"
    / "state"
    / "sophyane"
    / "tasks"
)


_FORBIDDEN_IMPORTS = {
    "smtplib",
    "subprocess",
    "pty",
    "pexpect",
}

_FORBIDDEN_CALLS = {
    "eval",
    "exec",
    "compile",
}

_FORBIDDEN_CLIENT_METHODS = {
    "store",
    "copy",
    "move",
    "expunge",
    "append",
    "create",
    "delete",
    "rename",
    "subscribe",
    "unsubscribe",
    "setacl",
    "setquota",
    "sendmail",
    "send_message",
}


def validate_generated_source(
    task: CompiledTask,
) -> list[str]:
    violations: list[str] = []

    try:
        tree = ast.parse(
            task.source_code
        )
    except SyntaxError as error:
        return [
            f"syntax:{error}"
        ]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(
                    ".",
                    1,
                )[0]

                if root in _FORBIDDEN_IMPORTS:
                    violations.append(
                        f"forbidden_import:{alias.name}"
                    )

        if isinstance(
            node,
            ast.ImportFrom,
        ):
            root = (
                str(node.module or "")
                .split(".", 1)[0]
            )

            if root in _FORBIDDEN_IMPORTS:
                violations.append(
                    "forbidden_import:"
                    + str(node.module)
                )

        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        func = node.func

        if (
            isinstance(func, ast.Name)
            and func.id
            in _FORBIDDEN_CALLS
        ):
            violations.append(
                f"forbidden_call:{func.id}"
            )

        if not isinstance(
            func,
            ast.Attribute,
        ):
            continue

        method = func.attr.lower()

        if method not in _FORBIDDEN_CLIENT_METHODS:
            continue

        receiver = func.value

        if (
            isinstance(receiver, ast.Name)
            and receiver.id
            in {
                "client",
                "imap",
                "conn",
                "connection",
                "mail",
                "m",
                "M",
            }
        ):
            violations.append(
                f"forbidden_authority:"
                f"{receiver.id}.{method}"
            )

    if "read" not in task.privileges:
        violations.append(
            "missing_read_authority"
        )

    if any(
        privilege
        in {
            "write",
            "execute_external",
            "send",
            "delete",
            "mutate",
        }
        for privilege in task.privileges
    ):
        violations.append(
            "unexpected_mutating_authority"
        )

    return sorted(
        set(violations)
    )


def _safe_task_id(value: str) -> str:
    return (
        re.sub(
            r"[^a-zA-Z0-9_.-]+",
            "-",
            value,
        ).strip("-")
        or "task"
    )


def execute_compiled_task(
    task: CompiledTask,
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    violations = (
        validate_generated_source(
            task
        )
    )

    if violations:
        return {
            "ok": False,
            "error": "source_validation_failed",
            "violations": violations,
        }

    STATE_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    stamp = time.strftime(
        "%Y%m%d-%H%M%S"
    )

    workspace = (
        STATE_ROOT
        / (
            stamp
            + "-"
            + _safe_task_id(
                task.task_id
            )
        )
    )

    workspace.mkdir(
        parents=True,
        exist_ok=False,
    )

    source_path = (
        workspace
        / task.filename
    )

    source_path.write_text(
        task.source_code,
        encoding="utf-8",
    )

    execution_env = dict(
        os.environ
    )

    if env:
        execution_env.update(
            {
                str(key): str(value)
                for key, value
                in env.items()
            }
        )

    try:
        process = subprocess.run(
            [
                sys.executable,
                str(source_path),
            ],
            cwd=str(workspace),
            env=execution_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=task.timeout_seconds,
            check=False,
        )

    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": "task_timeout",
            "workspace": str(workspace),
        }

    if process.returncode != 0:
        return {
            "ok": False,
            "error": "task_failed",
            "exit_code": process.returncode,
            "stderr": process.stderr[
                :4000
            ],
            "workspace": str(workspace),
        }

    try:
        payload = json.loads(
            process.stdout
        )
    except Exception as error:
        return {
            "ok": False,
            "error": "invalid_json_output",
            "message": str(error),
            "stdout": process.stdout[
                :4000
            ],
            "workspace": str(workspace),
        }

    return {
        "ok": True,
        "payload": payload,
        "workspace": str(workspace),
        "source_path": str(source_path),
    }


__all__ = [
    "execute_compiled_task",
    "validate_generated_source",
]
