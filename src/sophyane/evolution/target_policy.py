"""Repository-aware safety policy for cross-BADRPK evolution.

V2B remains deliberately conservative.

A TargetPolicy describes:

* paths that must never be mutated by evolution;
* source roots that actually exist in the selected repository;
* validator commands that can be discovered from repository metadata.

The policy does not itself patch anything and does not change
EvolutionEngine.repo.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .badrpk_targets import TargetSpec


COMMON_PROTECTED_NAMES: frozenset[str] = frozenset(
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
    }
)

COMMON_PROTECTED_FILES: frozenset[str] = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
    }
)

SOURCE_ROOT_CANDIDATES: tuple[str, ...] = (
    "src",
    "tests",
    "test",
    "app",
    "apps",
    "android",
    "public",
    "lib",
    "libs",
    "packages",
    "server",
    "backend",
    "frontend",
    "scripts",
    "tools",
)


@dataclass(frozen=True)
class ValidatorSpec:
    """One validator command discovered from repository structure."""

    name: str
    argv: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class TargetPolicy:
    """Resolved mutation and validation policy for one target."""

    name: str
    repo: Path
    source_roots: tuple[Path, ...]
    protected_names: frozenset[str]
    protected_files: frozenset[str]
    validators: tuple[ValidatorSpec, ...]

    def relative(self, path: Path) -> Path:
        resolved = Path(path).resolve()

        try:
            return resolved.relative_to(self.repo.resolve())
        except ValueError as error:
            raise ValueError(
                f"Path escapes target repository: {path}"
            ) from error

    def path_is_protected(self, path: Path) -> bool:
        relative = self.relative(path)

        parts = relative.parts

        if any(
            part in self.protected_names
            for part in parts
        ):
            return True

        if relative.name in self.protected_files:
            return True

        return False

    @property
    def mutable_roots(self) -> tuple[Path, ...]:
        """Roots eligible for V2C candidate mutation.

        Tests are validation material, not implementation mutation roots.
        """

        return tuple(
            root
            for root in self.source_roots
            if root not in {
                Path("test"),
                Path("tests"),
            }
        )

    @property
    def validation_roots(self) -> tuple[Path, ...]:
        """Test roots used for validation but not candidate mutation."""

        return tuple(
            root
            for root in self.source_roots
            if root in {
                Path("test"),
                Path("tests"),
            }
        )

    def path_is_mutable(self, path: Path) -> bool:
        """Return whether V2C may mutate this path."""

        if self.path_is_protected(path):
            return False

        relative = self.relative(path)

        if relative == Path("."):
            return False

        for root in self.mutable_roots:
            try:
                relative.relative_to(root)
            except ValueError:
                continue
            else:
                return True

        return False

    def path_is_candidate_source(self, path: Path) -> bool:
        if self.path_is_protected(path):
            return False

        relative = self.relative(path)

        if relative == Path("."):
            return False

        for root in self.source_roots:
            try:
                relative.relative_to(root)
            except ValueError:
                continue
            else:
                return True

        return False


def _existing_roots(repo: Path) -> tuple[Path, ...]:
    roots: list[Path] = []

    for name in SOURCE_ROOT_CANDIDATES:
        candidate = repo / name

        if candidate.exists():
            roots.append(Path(name))

    # Some BADRPK repositories may be intentionally small and keep
    # executable source directly at repository root. Do not silently
    # declare the whole repository mutable. V2B reports an empty root
    # set instead; later policy integration must explicitly opt in.
    return tuple(roots)


def _validator(
    name: str,
    argv: Iterable[str],
    reason: str,
) -> ValidatorSpec:
    return ValidatorSpec(
        name=name,
        argv=tuple(argv),
        reason=reason,
    )


def discover_validators(repo: Path) -> tuple[ValidatorSpec, ...]:
    """Discover conservative validators from repository metadata.

    Discovery is declarative only. No command is executed here.
    """

    repo = Path(repo).resolve()

    validators: list[ValidatorSpec] = []

    if (repo / "pyproject.toml").is_file():
        validators.append(
            _validator(
                "python-pytest",
                ("python3", "-m", "pytest", "-q"),
                "pyproject.toml present",
            )
        )

    elif (
        (repo / "pytest.ini").is_file()
        or (repo / "setup.cfg").is_file()
        or (repo / "tests").is_dir()
    ):
        validators.append(
            _validator(
                "python-pytest",
                ("python3", "-m", "pytest", "-q"),
                "Python test layout detected",
            )
        )

    if (repo / "package.json").is_file():
        if (repo / "package-lock.json").is_file():
            validators.append(
                _validator(
                    "npm-test",
                    ("npm", "test"),
                    "package.json + package-lock.json present",
                )
            )
        else:
            validators.append(
                _validator(
                    "npm-test",
                    ("npm", "test"),
                    "package.json present",
                )
            )

    if (repo / "gradlew").is_file():
        validators.append(
            _validator(
                "gradle-test",
                ("./gradlew", "test"),
                "Gradle wrapper present",
            )
        )

    if (repo / "Cargo.toml").is_file():
        validators.append(
            _validator(
                "cargo-test",
                ("cargo", "test"),
                "Cargo.toml present",
            )
        )

    if (repo / "go.mod").is_file():
        validators.append(
            _validator(
                "go-test",
                ("go", "test", "./..."),
                "go.mod present",
            )
        )

    return tuple(validators)


def build_target_policy(
    target: TargetSpec,
) -> TargetPolicy:
    """Build a policy without mutating the target repository."""

    repo = target.repo.resolve()

    if not repo.is_dir():
        raise FileNotFoundError(
            f"Target repository missing: {repo}"
        )

    if not target.git_repo:
        raise ValueError(
            f"Target is not a git repository: {repo}"
        )

    return TargetPolicy(
        name=target.name,
        repo=repo,
        source_roots=_existing_roots(repo),
        protected_names=COMMON_PROTECTED_NAMES,
        protected_files=COMMON_PROTECTED_FILES,
        validators=discover_validators(repo),
    )
