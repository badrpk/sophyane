"""Read-only Java/JDK discovery for BADRPK validation."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class JavaEnvironment:
    java: Path | None
    java_home: Path | None
    available: bool
    detail: str


def discover_java_environment() -> JavaEnvironment:
    java = shutil.which(
        "java"
    )

    java_home_raw = os.getenv(
        "JAVA_HOME"
    )

    java_home = (
        Path(java_home_raw)
        .expanduser()
        .resolve()
        if java_home_raw
        else None
    )

    candidates: list[
        Path
    ] = []

    if java:
        candidates.append(
            Path(java)
        )

    roots = (
        Path(
            "/data/data/com.termux/files/usr/lib/jvm"
        ),
        Path(
            "/data/data/com.termux/files/usr/opt"
        ),
        Path.home()
        / ".jdks",
    )

    for root in roots:
        if not root.is_dir():
            continue

        for candidate in root.glob(
            "**/bin/java"
        ):
            if candidate.is_file():
                candidates.append(
                    candidate
                )

    seen: set[
        Path
    ] = set()

    for candidate in candidates:
        try:
            candidate = candidate.resolve()
        except OSError:
            continue

        if candidate in seen:
            continue

        seen.add(
            candidate
        )

        try:
            completed = subprocess.run(
                (
                    str(candidate),
                    "-version",
                ),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15,
            )

        except Exception:
            continue

        if completed.returncode != 0:
            continue

        inferred_home = (
            candidate.parent.parent
        )

        output = (
            completed.stderr.strip()
            or completed.stdout.strip()
        )

        return JavaEnvironment(
            java=candidate,
            java_home=(
                java_home
                or inferred_home
            ),
            available=True,
            detail=output.splitlines()[0],
        )

    return JavaEnvironment(
        java=None,
        java_home=java_home,
        available=False,
        detail=(
            "No runnable Java binary discovered"
        ),
    )
