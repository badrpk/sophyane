"""Repository-wide validation topology for BADRPK targets.

Validation discovery is intentionally broader than mutation policy.

A repository may contain validator-bearing projects outside paths that
Sophyane is permitted to mutate. V2E therefore scans the repository for
validation metadata independently while retaining TargetPolicy as the
authority for mutation.

Discovery never executes validators and never modifies the repository.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .python_validation_environment import (
    resolve_pytest_python,
)


MAX_SCAN_DEPTH = 8

SKIP_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".github",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".gradle",
        ".idea",
        ".cache",
        "dist",
        "build",
        "coverage",
        ".next",
    }
)


@dataclass(frozen=True)
class ValidationNode:
    """One validator-bearing project discovered in a repository."""

    kind: str
    cwd: Path
    argv: tuple[str, ...]
    metadata: str
    runnable: bool
    reason: str

    @property
    def key(self) -> tuple[str, str]:
        return (
            self.kind,
            str(self.cwd),
        )


@dataclass(frozen=True)
class ValidationTopology:
    """Repository-wide set of baseline validation nodes."""

    target_name: str
    repo: Path
    nodes: tuple[ValidationNode, ...]
    diagnostics: tuple[str, ...]

    @property
    def runnable(self) -> tuple[ValidationNode, ...]:
        return tuple(
            node
            for node in self.nodes
            if node.runnable
        )

    @property
    def unavailable(self) -> tuple[ValidationNode, ...]:
        return tuple(
            node
            for node in self.nodes
            if not node.runnable
        )

    @property
    def readiness(self) -> str:
        if not self.nodes:
            return "NO_VALIDATOR"

        if self.unavailable:
            return "PARTIAL"

        return "READY"


def _which(
    command: str,
) -> str | None:
    return shutil.which(command)


def _depth(
    repo: Path,
    path: Path,
) -> int:
    relative = path.relative_to(
        repo
    )

    if relative == Path("."):
        return 0

    return len(
        relative.parts
    )


def _iter_dirs(
    repo: Path,
):
    repo = repo.resolve()

    for current, dirs, files in os.walk(
        repo
    ):
        current_path = Path(
            current
        ).resolve()

        depth = _depth(
            repo,
            current_path,
        )

        dirs[:] = [
            name
            for name in dirs
            if (
                name not in SKIP_NAMES
                and not name.startswith(
                    ".sophyane-evolution"
                )
                and not name.startswith(
                    ".evolution-"
                )
            )
        ]

        if depth >= MAX_SCAN_DEPTH:
            dirs[:] = []

        yield (
            current_path,
            set(files),
        )


def _python_interpreters(
    repo: Path,
    cwd: Path,
) -> tuple[Path, ...]:
    possibilities = (
        cwd / ".venv" / "bin" / "python",
        cwd / "venv" / "bin" / "python",
        repo / ".venv" / "bin" / "python",
        repo / "venv" / "bin" / "python",
        Path.home()
        / ".local"
        / "share"
        / "sophyane"
        / "venv"
        / "bin"
        / "python",
    )

    found: list[Path] = []

    for candidate in possibilities:
        try:
            path = candidate.resolve()
        except OSError:
            continue

        if (
            path.is_file()
            and os.access(
                path,
                os.X_OK,
            )
            and path not in found
        ):
            found.append(path)

    global_python = _which(
        "python3"
    )

    if global_python:
        path = Path(
            global_python
        ).resolve()

        if path not in found:
            found.append(path)

    return tuple(found)


def _can_import_pytest(
    python: Path,
    cwd: Path,
) -> bool:
    try:
        completed = subprocess.run(
            (
                str(python),
                "-c",
                "import pytest",
            ),
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
        )

    except (
        OSError,
        subprocess.TimeoutExpired,
    ):
        return False

    return completed.returncode == 0


def _pytest_node(
    repo: Path,
    cwd: Path,
    metadata: str,
) -> ValidationNode:
    environment = resolve_pytest_python(
        repo=repo,
        cwd=cwd,
        harness_repo=(
            Path.home()
            / "sophyane"
        ),
    )

    if environment is not None:
        return ValidationNode(
            kind="python-pytest",
            cwd=cwd,
            argv=(
                str(
                    environment.python
                ),
                "-m",
                "pytest",
                "-q",
            ),
            metadata=metadata,
            runnable=True,
            reason=(
                f"{environment.source}: "
                f"{environment.reason}"
            ),
        )

    return ValidationNode(
        kind="python-pytest",
        cwd=cwd,
        argv=(
            "python3",
            "-m",
            "pytest",
            "-q",
        ),
        metadata=metadata,
        runnable=False,
        reason=(
            "no discovered Python interpreter "
            "can import pytest"
        ),
    )

def _npm_node(
    cwd: Path,
) -> tuple[
    ValidationNode | None,
    str | None,
]:
    package = cwd / "package.json"

    try:
        data = json.loads(
            package.read_text(
                encoding="utf-8"
            )
        )

    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as error:
        return (
            None,
            (
                f"{package}: unreadable package.json: "
                f"{type(error).__name__}: {error}"
            ),
        )

    script = (
        data.get(
            "scripts",
            {},
        )
        .get("test")
    )

    # A package without a test script is not automatically a failed
    # validator requirement. It simply contributes no validator node.
    if not isinstance(
        script,
        str,
    ):
        return (
            None,
            None,
        )

    script = script.strip()

    if not script:
        return (
            None,
            None,
        )

    if (
        "no test specified"
        in script.casefold()
    ):
        return (
            None,
            (
                f"{package}: placeholder test script ignored"
            ),
        )

    runnable = (
        _which("npm")
        is not None
    )

    return (
        ValidationNode(
            kind="npm-test",
            cwd=cwd,
            argv=(
                "npm",
                "test",
            ),
            metadata="package.json scripts.test",
            runnable=runnable,
            reason=(
                "npm executable and real test script verified"
                if runnable
                else "npm unavailable"
            ),
        ),
        None,
    )


def _gradle_node(
    cwd: Path,
) -> ValidationNode:
    wrapper = cwd / "gradlew"

    runnable = (
        wrapper.is_file()
        and os.access(
            wrapper,
            os.X_OK,
        )
    )

    return ValidationNode(
        kind="gradle-test",
        cwd=cwd,
        argv=(
            "./gradlew",
            "test",
        ),
        metadata="gradlew",
        runnable=runnable,
        reason=(
            "executable Gradle wrapper verified"
            if runnable
            else "gradlew is not executable"
        ),
    )


def _cargo_node(
    cwd: Path,
) -> ValidationNode:
    runnable = (
        _which("cargo")
        is not None
    )

    return ValidationNode(
        kind="cargo-test",
        cwd=cwd,
        argv=(
            "cargo",
            "test",
        ),
        metadata="Cargo.toml",
        runnable=runnable,
        reason=(
            "cargo executable verified"
            if runnable
            else "cargo unavailable"
        ),
    )


def _go_node(
    cwd: Path,
) -> ValidationNode:
    runnable = (
        _which("go")
        is not None
    )

    return ValidationNode(
        kind="go-test",
        cwd=cwd,
        argv=(
            "go",
            "test",
            "./...",
        ),
        metadata="go.mod",
        runnable=runnable,
        reason=(
            "go executable verified"
            if runnable
            else "go unavailable"
        ),
    )


def discover_validation_topology(
    *,
    target_name: str,
    repo: Path,
) -> ValidationTopology:
    repo = Path(
        repo
    ).resolve()

    nodes: list[ValidationNode] = []
    diagnostics: list[str] = []

    seen: set[
        tuple[
            str,
            str,
        ]
    ] = set()

    for cwd, files in _iter_dirs(
        repo
    ):
        python_signal = (
            "pytest.ini" in files
            or (
                cwd / "tests"
            ).is_dir()
            or (
                cwd / "test"
            ).is_dir()
        )

        if python_signal:
            node = _pytest_node(
                repo,
                cwd,
                (
                    "pytest.ini/test directory "
                    "detected"
                ),
            )

            if node.key not in seen:
                seen.add(
                    node.key
                )
                nodes.append(
                    node
                )

        if "package.json" in files:
            node, diagnostic = _npm_node(
                cwd
            )

            if diagnostic:
                diagnostics.append(
                    diagnostic
                )

            if (
                node is not None
                and node.key not in seen
            ):
                seen.add(
                    node.key
                )
                nodes.append(
                    node
                )

        if "gradlew" in files:
            node = _gradle_node(
                cwd
            )

            if node.key not in seen:
                seen.add(
                    node.key
                )
                nodes.append(
                    node
                )

        if "Cargo.toml" in files:
            node = _cargo_node(
                cwd
            )

            if node.key not in seen:
                seen.add(
                    node.key
                )
                nodes.append(
                    node
                )

        if "go.mod" in files:
            node = _go_node(
                cwd
            )

            if node.key not in seen:
                seen.add(
                    node.key
                )
                nodes.append(
                    node
                )

    return ValidationTopology(
        target_name=target_name,
        repo=repo,
        nodes=tuple(
            nodes
        ),
        diagnostics=tuple(
            diagnostics
        ),
    )
