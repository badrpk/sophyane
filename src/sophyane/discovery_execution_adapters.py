"""Bounded software experiment execution for Sophyane discovery.

Only Python experiments using the explicit PYTHON_SOURCE protocol are
supported. No shell execution is performed here.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile

from pathlib import Path
from typing import Any

from sophyane.discovery_contract import (
    Observation,
)


SOURCE_PREFIX = "PYTHON_SOURCE:"

MAX_SOURCE_CHARACTERS = 30000
MAX_OUTPUT_CHARACTERS = 20000
DEFAULT_TIMEOUT_SECONDS = 20


_ALLOWED_IMPORT_ROOTS = {
    "collections",
    "functools",
    "itertools",
    "json",
    "math",
    "random",
    "statistics",
}

_BLOCKED_CALL_NAMES = {
    "__import__",
    "breakpoint",
    "compile",
    "eval",
    "exec",
    "input",
    "open",
}

_BLOCKED_ROOT_NAMES = {
    "asyncio",
    "builtins",
    "ctypes",
    "http",
    "multiprocessing",
    "os",
    "pathlib",
    "requests",
    "shutil",
    "socket",
    "subprocess",
    "sys",
    "urllib",
}


class UnsafeExperimentError(
    RuntimeError
):
    pass


def _plan_steps(
    plan: object,
) -> tuple[str, ...]:
    value = getattr(
        plan,
        "procedure",
        (),
    )

    if isinstance(
        value,
        str,
    ):
        return (
            value,
        )

    try:
        return tuple(
            str(item)
            for item in value
        )
    except Exception:
        return ()


def extract_python_source(
    plan: object,
) -> str:
    for step in _plan_steps(
        plan
    ):
        stripped = step.strip()

        if stripped.startswith(
            SOURCE_PREFIX
        ):
            source = stripped[
                len(
                    SOURCE_PREFIX
                ):
            ].lstrip()

            if not source:
                raise UnsafeExperimentError(
                    "EMPTY_PYTHON_SOURCE"
                )

            if len(
                source
            ) > MAX_SOURCE_CHARACTERS:
                raise UnsafeExperimentError(
                    "PYTHON_SOURCE_TOO_LARGE"
                )

            return source

    raise UnsafeExperimentError(
        "PYTHON_SOURCE_PROTOCOL_REQUIRED"
    )


def _root_name(
    node: ast.AST,
) -> str:
    current = node

    while isinstance(
        current,
        ast.Attribute,
    ):
        current = current.value

    if isinstance(
        current,
        ast.Name,
    ):
        return current.id

    return ""


def validate_python_source(
    source: str,
) -> None:
    try:
        tree = ast.parse(
            source,
            mode="exec",
        )
    except SyntaxError as exc:
        raise UnsafeExperimentError(
            "INVALID_PYTHON_SOURCE"
        ) from exc

    for node in ast.walk(
        tree
    ):
        if isinstance(
            node,
            (
                ast.Import,
                ast.ImportFrom,
            ),
        ):
            if isinstance(
                node,
                ast.Import,
            ):
                modules = [
                    alias.name
                    for alias in node.names
                ]
            else:
                modules = [
                    str(
                        node.module
                        or ""
                    )
                ]

            for module in modules:
                root = (
                    module
                    .split(
                        ".",
                        1,
                    )[0]
                )

                if (
                    not root
                    or root
                    not in _ALLOWED_IMPORT_ROOTS
                ):
                    raise UnsafeExperimentError(
                        "IMPORT_BLOCKED:"
                        + root
                    )

        if isinstance(
            node,
            ast.Call,
        ):
            if isinstance(
                node.func,
                ast.Name,
            ):
                if node.func.id in (
                    _BLOCKED_CALL_NAMES
                ):
                    raise UnsafeExperimentError(
                        "CALL_BLOCKED:"
                        + node.func.id
                    )

            root = _root_name(
                node.func
            )

            if root in (
                _BLOCKED_ROOT_NAMES
            ):
                raise UnsafeExperimentError(
                    "API_BLOCKED:"
                    + root
                )

        if isinstance(
            node,
            ast.Attribute,
        ):
            root = _root_name(
                node
            )

            if root in (
                _BLOCKED_ROOT_NAMES
            ):
                raise UnsafeExperimentError(
                    "ATTRIBUTE_ROOT_BLOCKED:"
                    + root
                )


def _parse_result_payload(
    stdout: str,
) -> dict[str, Any]:
    lines = [
        line.strip()
        for line in stdout.splitlines()
        if line.strip()
    ]

    for line in reversed(
        lines
    ):
        try:
            parsed = json.loads(
                line
            )
        except Exception:
            continue

        if isinstance(
            parsed,
            dict,
        ):
            return parsed

    return {}


def _numeric(
    value: object,
) -> float | None:
    if isinstance(
        value,
        bool,
    ):
        return None

    if isinstance(
        value,
        (
            int,
            float,
        ),
    ):
        return float(
            value
        )

    return None


def _deterministic_improvement(
    measurements: dict[str, Any],
) -> bool:
    baseline = _numeric(
        measurements.get(
            "baseline_score"
        )
    )

    candidate = _numeric(
        measurements.get(
            "candidate_score"
        )
    )

    if (
        baseline is None
        or candidate is None
    ):
        return False

    return candidate > baseline


def execute_python_experiment(
    plan: object,
    workspace: str,
    *,
    timeout_seconds: int = (
        DEFAULT_TIMEOUT_SECONDS
    ),
) -> Observation:
    experiment_id = str(
        getattr(
            plan,
            "experiment_id",
            "",
        )
        or ""
    )

    try:
        source = extract_python_source(
            plan
        )

        validate_python_source(
            source
        )

    except UnsafeExperimentError as exc:
        return Observation(
            experiment_id=experiment_id,
            executed=False,
            ok=False,
            output="",
            measurements={},
            evidence={
                "reason": str(
                    exc
                ),
                "executor": (
                    "safe_python"
                ),
            },
        )

    root = Path(
        workspace
    ).resolve()

    root.mkdir(
        parents=True,
        exist_ok=True,
    )

    timeout = max(
        1,
        min(
            int(
                timeout_seconds
            ),
            60,
        ),
    )

    env = {
        "PATH": os.environ.get(
            "PATH",
            "",
        ),
        "HOME": str(
            root
        ),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONHASHSEED": "0",
    }

    try:
        with tempfile.TemporaryDirectory(
            prefix="sophyane-discovery-",
            dir=str(
                root
            ),
        ) as td:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    "-c",
                    source,
                ],
                cwd=td,
                env=env,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )

    except subprocess.TimeoutExpired as exc:
        return Observation(
            experiment_id=experiment_id,
            executed=True,
            ok=False,
            output=(
                "EXPERIMENT_TIMEOUT"
            ),
            measurements={},
            evidence={
                "reason": (
                    "EXPERIMENT_TIMEOUT"
                ),
                "timeout_seconds": timeout,
                "executor": (
                    "safe_python"
                ),
            },
        )

    stdout = (
        completed.stdout
        or ""
    )[
        -MAX_OUTPUT_CHARACTERS:
    ]

    stderr = (
        completed.stderr
        or ""
    )[
        -MAX_OUTPUT_CHARACTERS:
    ]

    payload = _parse_result_payload(
        stdout
    )

    measurements = payload.get(
        "measurements",
        {},
    )

    if not isinstance(
        measurements,
        dict,
    ):
        measurements = {}

    # Convenience protocol: allow scores at
    # top level as well.
    for key in (
        "baseline_score",
        "candidate_score",
    ):
        if (
            key in payload
            and key not in measurements
        ):
            measurements[
                key
            ] = payload[
                key
            ]

    exit_zero = (
        completed.returncode
        == 0
    )

    improvement = (
        exit_zero
        and _deterministic_improvement(
            measurements
        )
    )

    evidence = {
        "executor": (
            "safe_python"
        ),
        "exit_code": (
            completed.returncode
        ),
        "execution_exit_zero": (
            exit_zero
        ),
        "deterministic_verified": (
            improvement
        ),
        "stdout": stdout,
        "stderr": stderr,
    }

    return Observation(
        experiment_id=experiment_id,
        executed=True,
        ok=exit_zero,
        output=stdout,
        measurements=measurements,
        evidence=evidence,
    )


def code_executor(
    plan: object,
    workspace: str,
) -> Observation:
    return execute_python_experiment(
        plan,
        workspace,
    )


def simulation_executor(
    plan: object,
    workspace: str,
) -> Observation:
    return execute_python_experiment(
        plan,
        workspace,
    )


__all__ = [
    "UnsafeExperimentError",
    "code_executor",
    "execute_python_experiment",
    "extract_python_source",
    "simulation_executor",
    "validate_python_source",
]
