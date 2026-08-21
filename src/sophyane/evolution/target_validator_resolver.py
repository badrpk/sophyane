"""Repository-aware validator resolution for BADRPK targets.

V2D supplements the conservative root-level V2B discovery.

It recursively inspects a bounded set of source/project directories while:

* avoiding protected/generated trees;
* never installing dependencies;
* never executing tests during discovery;
* never modifying the target repository;
* keeping unresolved validators fail-closed.

The resulting ValidatorCandidate contains an explicit cwd so nested projects
such as apps/foo/package.json can be validated in their own project directory.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .target_policy import TargetPolicy


MAX_PROJECT_DEPTH = 4

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
        "dist",
        "build",
        ".gradle",
        ".idea",
        ".cache",
    }
)


@dataclass(frozen=True)
class ValidatorCandidate:
    """One repository-aware validator candidate."""

    name: str
    cwd: Path
    argv: tuple[str, ...]
    source: str
    runnable: bool
    reason: str

    @property
    def command(self) -> str:
        return " ".join(self.argv)


@dataclass(frozen=True)
class RepositoryValidationProfile:
    """Resolved V2D validator state for one repository."""

    target_name: str
    repo: Path
    candidates: tuple[ValidatorCandidate, ...]

    @property
    def runnable(self) -> tuple[ValidatorCandidate, ...]:
        return tuple(
            item
            for item in self.candidates
            if item.runnable
        )

    @property
    def unavailable(self) -> tuple[ValidatorCandidate, ...]:
        return tuple(
            item
            for item in self.candidates
            if not item.runnable
        )

    @property
    def readiness(self) -> str:
        if not self.candidates:
            return "NO_VALIDATOR"

        if self.unavailable:
            return "NOT_READY"

        return "READY"


def _relative_depth(
    base: Path,
    path: Path,
) -> int:
    relative = path.relative_to(base)

    if relative == Path("."):
        return 0

    return len(relative.parts)


def _walk_project_dirs(
    repo: Path,
    policy: TargetPolicy,
) -> tuple[Path, ...]:
    """Return bounded project directories under known source roots."""

    repo = repo.resolve()

    candidates: set[Path] = {
        repo,
    }

    for relative_root in policy.source_roots:
        root = (
            repo
            / relative_root
        ).resolve()

        if not root.is_dir():
            continue

        candidates.add(root)

        for current, dirs, _files in os.walk(root):
            current_path = Path(current)

            depth = _relative_depth(
                root,
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
                )
            ]

            if depth >= MAX_PROJECT_DEPTH:
                dirs[:] = []
                continue

            candidates.add(
                current_path.resolve()
            )

    return tuple(
        sorted(
            candidates,
            key=lambda path: str(path),
        )
    )


def _which(
    command: str,
) -> str | None:
    return shutil.which(command)


def _python_candidates(
    repo: Path,
    cwd: Path,
) -> tuple[Path, ...]:
    found: list[Path] = []

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

    for path in possibilities:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            continue

        if (
            resolved.is_file()
            and os.access(
                resolved,
                os.X_OK,
            )
            and resolved not in found
        ):
            found.append(resolved)

    global_python = _which("python3")

    if global_python:
        resolved = Path(
            global_python
        ).resolve()

        if resolved not in found:
            found.append(resolved)

    return tuple(found)


def _python_has_pytest(
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


def _resolve_pytest(
    repo: Path,
    cwd: Path,
    source: str,
) -> ValidatorCandidate:
    interpreters = _python_candidates(
        repo,
        cwd,
    )

    for interpreter in interpreters:
        if _python_has_pytest(
            interpreter,
            cwd,
        ):
            return ValidatorCandidate(
                name="python-pytest",
                cwd=cwd,
                argv=(
                    str(interpreter),
                    "-m",
                    "pytest",
                    "-q",
                ),
                source=source,
                runnable=True,
                reason=(
                    "pytest import verified with "
                    f"{interpreter}"
                ),
            )

    return ValidatorCandidate(
        name="python-pytest",
        cwd=cwd,
        argv=(
            "python3",
            "-m",
            "pytest",
            "-q",
        ),
        source=source,
        runnable=False,
        reason=(
            "no discovered Python interpreter "
            "can import pytest"
        ),
    )


def _resolve_npm(
    cwd: Path,
) -> ValidatorCandidate:
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
    ):
        return ValidatorCandidate(
            name="npm-test",
            cwd=cwd,
            argv=(
                "npm",
                "test",
            ),
            source="package.json",
            runnable=False,
            reason="package.json unreadable",
        )

    script = (
        data.get(
            "scripts",
            {},
        )
        .get("test")
    )

    if not isinstance(
        script,
        str,
    ):
        return ValidatorCandidate(
            name="npm-test",
            cwd=cwd,
            argv=(
                "npm",
                "test",
            ),
            source="package.json",
            runnable=False,
            reason="package.json has no test script",
        )

    script = script.strip()

    if not script:
        return ValidatorCandidate(
            name="npm-test",
            cwd=cwd,
            argv=(
                "npm",
                "test",
            ),
            source="package.json",
            runnable=False,
            reason="package test script is empty",
        )

    if (
        "no test specified"
        in script.casefold()
    ):
        return ValidatorCandidate(
            name="npm-test",
            cwd=cwd,
            argv=(
                "npm",
                "test",
            ),
            source="package.json",
            runnable=False,
            reason="placeholder npm test script",
        )

    if _which("npm") is None:
        return ValidatorCandidate(
            name="npm-test",
            cwd=cwd,
            argv=(
                "npm",
                "test",
            ),
            source="package.json",
            runnable=False,
            reason="npm unavailable",
        )

    return ValidatorCandidate(
        name="npm-test",
        cwd=cwd,
        argv=(
            "npm",
            "test",
        ),
        source="package.json",
        runnable=True,
        reason=(
            "npm executable and test script verified"
        ),
    )


def _resolve_gradle(
    cwd: Path,
) -> ValidatorCandidate:
    wrapper = cwd / "gradlew"

    if not wrapper.is_file():
        return ValidatorCandidate(
            name="gradle-test",
            cwd=cwd,
            argv=(
                "./gradlew",
                "test",
            ),
            source="gradlew",
            runnable=False,
            reason="gradlew missing",
        )

    if not os.access(
        wrapper,
        os.X_OK,
    ):
        return ValidatorCandidate(
            name="gradle-test",
            cwd=cwd,
            argv=(
                "./gradlew",
                "test",
            ),
            source="gradlew",
            runnable=False,
            reason="gradlew not executable",
        )

    return ValidatorCandidate(
        name="gradle-test",
        cwd=cwd,
        argv=(
            "./gradlew",
            "test",
        ),
        source="gradlew",
        runnable=True,
        reason="executable Gradle wrapper verified",
    )


def _resolve_cargo(
    cwd: Path,
) -> ValidatorCandidate:
    available = (
        _which("cargo")
        is not None
    )

    return ValidatorCandidate(
        name="cargo-test",
        cwd=cwd,
        argv=(
            "cargo",
            "test",
        ),
        source="Cargo.toml",
        runnable=available,
        reason=(
            "cargo executable verified"
            if available
            else "cargo unavailable"
        ),
    )


def _resolve_go(
    cwd: Path,
) -> ValidatorCandidate:
    available = (
        _which("go")
        is not None
    )

    return ValidatorCandidate(
        name="go-test",
        cwd=cwd,
        argv=(
            "go",
            "test",
            "./...",
        ),
        source="go.mod",
        runnable=available,
        reason=(
            "go executable verified"
            if available
            else "go unavailable"
        ),
    )


def resolve_repository_validators(
    *,
    target_name: str,
    repo: Path,
    policy: TargetPolicy,
) -> RepositoryValidationProfile:
    """Discover and resolve nested validators without executing tests."""

    repo = Path(repo).resolve()

    candidates: list[ValidatorCandidate] = []

    seen: set[
        tuple[
            str,
            str,
        ]
    ] = set()

    for cwd in _walk_project_dirs(
        repo,
        policy,
    ):
        manifests = {
            path.name
            for path in cwd.iterdir()
            if path.is_file()
        }

        python_signal = (
            "pyproject.toml" in manifests
            or "pytest.ini" in manifests
            or "setup.cfg" in manifests
            or (
                cwd / "tests"
            ).is_dir()
        )

        if python_signal:
            key = (
                "python-pytest",
                str(cwd),
            )

            if key not in seen:
                seen.add(key)

                candidates.append(
                    _resolve_pytest(
                        repo,
                        cwd,
                        (
                            "Python project/test "
                            "metadata detected"
                        ),
                    )
                )

        if "package.json" in manifests:
            key = (
                "npm-test",
                str(cwd),
            )

            if key not in seen:
                seen.add(key)

                candidates.append(
                    _resolve_npm(
                        cwd
                    )
                )

        if "gradlew" in manifests:
            key = (
                "gradle-test",
                str(cwd),
            )

            if key not in seen:
                seen.add(key)

                candidates.append(
                    _resolve_gradle(
                        cwd
                    )
                )

        if "Cargo.toml" in manifests:
            key = (
                "cargo-test",
                str(cwd),
            )

            if key not in seen:
                seen.add(key)

                candidates.append(
                    _resolve_cargo(
                        cwd
                    )
                )

        if "go.mod" in manifests:
            key = (
                "go-test",
                str(cwd),
            )

            if key not in seen:
                seen.add(key)

                candidates.append(
                    _resolve_go(
                        cwd
                    )
                )

    return RepositoryValidationProfile(
        target_name=target_name,
        repo=repo,
        candidates=tuple(
            candidates
        ),
    )
