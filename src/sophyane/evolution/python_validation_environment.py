"""Python execution environment resolution for BADRPK validation.

This module resolves already-existing interpreters only.

It performs no installation and modifies no environment.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PythonEnvironment:
    python: Path
    pytest_available: bool
    pytest_version: str | None
    source: str
    reason: str


def _candidate_paths(
    *,
    repo: Path,
    cwd: Path,
    harness_repo: Path | None = None,
) -> tuple[tuple[Path, str], ...]:
    candidates: list[
        tuple[Path, str]
    ] = []

    def add(
        path: Path,
        source: str,
    ) -> None:
        # CRITICAL:
        # Never Path.resolve() a virtual-environment interpreter.
        #
        # venv/bin/python is commonly a symlink to the system Python.
        # Following that symlink destroys the venv invocation identity
        # and can make packages installed only in the venv disappear.
        #
        # We want an absolute filesystem spelling while preserving the
        # executable symlink itself.
        try:
            executable = Path(
                os.path.abspath(
                    os.fspath(
                        path.expanduser()
                    )
                )
            )
        except (
            OSError,
            TypeError,
            ValueError,
        ):
            return

        if any(
            existing == executable
            for existing, _source in candidates
        ):
            return

        candidates.append(
            (
                executable,
                source,
            )
        )

    add(
        cwd / ".venv" / "bin" / "python",
        "project .venv",
    )

    add(
        cwd / "venv" / "bin" / "python",
        "project venv",
    )

    add(
        repo / ".venv" / "bin" / "python",
        "target .venv",
    )

    add(
        repo / "venv" / "bin" / "python",
        "target venv",
    )

    if harness_repo is not None:
        add(
            harness_repo
            / ".venv"
            / "bin"
            / "python",
            "Sophyane harness .venv",
        )

    add(
        Path.home()
        / "sophyane"
        / ".venv"
        / "bin"
        / "python",
        "active Sophyane development .venv",
    )

    add(
        Path.home()
        / ".local"
        / "share"
        / "sophyane"
        / "venv"
        / "bin"
        / "python",
        "managed Sophyane venv",
    )

    add(
        Path.home()
        / "badrmart-benchmark"
        / "tools"
        / "sophyane-venv"
        / "bin"
        / "python",
        "benchmark Sophyane venv",
    )

    global_python = shutil.which(
        "python3"
    )

    if global_python:
        add(
            Path(global_python),
            "PATH python3",
        )

    return tuple(
        candidates
    )


def inspect_python(
    python: Path,
    source: str,
    *,
    cwd: Path,
) -> PythonEnvironment:
    if not python.is_file():
        return PythonEnvironment(
            python=python,
            pytest_available=False,
            pytest_version=None,
            source=source,
            reason="interpreter absent",
        )

    if not os.access(
        python,
        os.X_OK,
    ):
        return PythonEnvironment(
            python=python,
            pytest_available=False,
            pytest_version=None,
            source=source,
            reason="interpreter not executable",
        )

    probe = (
        "import sys; "
        "print(sys.executable); "
        "import pytest; "
        "print(pytest.__version__)"
    )

    try:
        completed = subprocess.run(
            (
                str(python),
                "-c",
                probe,
            ),
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
        )

    except Exception as error:
        return PythonEnvironment(
            python=python,
            pytest_available=False,
            pytest_version=None,
            source=source,
            reason=(
                f"{type(error).__name__}: {error}"
            ),
        )

    if completed.returncode != 0:
        return PythonEnvironment(
            python=python,
            pytest_available=False,
            pytest_version=None,
            source=source,
            reason=(
                completed.stderr.strip()
                or "pytest probe failed"
            ),
        )

    lines = [
        line.strip()
        for line in completed.stdout.splitlines()
        if line.strip()
    ]

    version = (
        lines[-1]
        if lines
        else None
    )

    return PythonEnvironment(
        python=python,
        pytest_available=True,
        pytest_version=version,
        source=source,
        reason=(
            f"pytest {version} available"
        ),
    )


def discover_python_environments(
    *,
    repo: Path,
    cwd: Path,
    harness_repo: Path | None = None,
) -> tuple[PythonEnvironment, ...]:
    return tuple(
        inspect_python(
            path,
            source,
            cwd=cwd,
        )
        for path, source in _candidate_paths(
            repo=repo,
            cwd=cwd,
            harness_repo=harness_repo,
        )
        if path.exists()
    )


def resolve_pytest_python(
    *,
    repo: Path,
    cwd: Path,
    harness_repo: Path | None = None,
) -> PythonEnvironment | None:
    for environment in discover_python_environments(
        repo=repo,
        cwd=cwd,
        harness_repo=harness_repo,
    ):
        if environment.pytest_available:
            return environment

    return None
