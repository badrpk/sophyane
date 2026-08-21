"""Local execution-environment diagnostics for BADRPK validation."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EnvironmentCapability:
    name: str
    available: bool
    detail: str


def _command_version(
    command: str,
    *args: str,
) -> EnvironmentCapability:
    path = shutil.which(
        command
    )

    if path is None:
        return EnvironmentCapability(
            command,
            False,
            f"{command} not found in PATH",
        )

    try:
        result = subprocess.run(
            (
                path,
                *args,
            ),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
        )

    except Exception as error:
        return EnvironmentCapability(
            command,
            False,
            (
                f"{path}: {type(error).__name__}: "
                f"{error}"
            ),
        )

    output = (
        result.stdout.strip()
        or result.stderr.strip()
    )

    return EnvironmentCapability(
        command,
        result.returncode == 0,
        (
            f"{path}: "
            + output.splitlines()[0]
            if output
            else str(path)
        ),
    )


def discover_environment_capabilities() -> tuple[
    EnvironmentCapability,
    ...,
]:
    capabilities: list[
        EnvironmentCapability
    ] = []

    java = _command_version(
        "java",
        "-version",
    )

    java_home = os.getenv(
        "JAVA_HOME"
    )

    if java.available:
        capabilities.append(
            EnvironmentCapability(
                "java",
                True,
                (
                    f"{java.detail}; "
                    f"JAVA_HOME={java_home!r}"
                ),
            )
        )
    else:
        capabilities.append(
            EnvironmentCapability(
                "java",
                False,
                (
                    f"{java.detail}; "
                    f"JAVA_HOME={java_home!r}"
                ),
            )
        )

    capabilities.extend(
        (
            _command_version(
                "npm",
                "--version",
            ),
            _command_version(
                "node",
                "--version",
            ),
            _command_version(
                "cargo",
                "--version",
            ),
            _command_version(
                "rustc",
                "--version",
            ),
            _command_version(
                "python3",
                "--version",
            ),
        )
    )

    python_candidates = (
        Path.home()
        / "sophyane"
        / ".venv"
        / "bin"
        / "python",

        Path.home()
        / ".local"
        / "share"
        / "sophyane"
        / "venv"
        / "bin"
        / "python",

        Path.home()
        / "badrmart-benchmark"
        / "tools"
        / "sophyane-venv"
        / "bin"
        / "python",
    )

    for python in python_candidates:
        if not python.is_file():
            continue

        try:
            result = subprocess.run(
                (
                    str(python),
                    "-c",
                    (
                        "import sys; "
                        "print(sys.executable); "
                        "import pytest; "
                        "print(pytest.__version__)"
                    ),
                ),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15,
            )

        except Exception as error:
            capabilities.append(
                EnvironmentCapability(
                    f"pytest:{python}",
                    False,
                    (
                        f"{type(error).__name__}: "
                        f"{error}"
                    ),
                )
            )
            continue

        capabilities.append(
            EnvironmentCapability(
                f"pytest:{python}",
                result.returncode == 0,
                (
                    result.stdout.strip()
                    if result.returncode == 0
                    else result.stderr.strip()
                ),
            )
        )

    return tuple(
        capabilities
    )
