"""BADRPK repository targets for Sophyane evolution.

This module deliberately separates two concepts:

* harness repository:
    The Sophyane source tree whose executable runs the evolution process.

* target repository:
    The BADRPK source tree that an evolution cycle may eventually inspect,
    validate, or modify.

V2A resolves and describes targets only. Existing EvolutionEngine execution,
patching, worktree creation, validation, and promotion continue to operate on
the Sophyane harness repository until later integration explicitly opts into a
target-aware gate.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BADRPK_REPOSITORY_NAMES: tuple[str, ...] = (
    "Droidra",
    "rangoons",
    "xerus",
    "sophyane",
    "shmry",
    "Veyron",
)


@dataclass(frozen=True)
class TargetSpec:
    """Resolved BADRPK evolution target."""

    name: str
    repo: Path
    harness_repo: Path

    @property
    def exists(self) -> bool:
        return self.repo.is_dir()

    @property
    def git_repo(self) -> bool:
        return (self.repo / ".git").exists()

    @property
    def is_harness(self) -> bool:
        try:
            return self.repo.resolve() == self.harness_repo.resolve()
        except OSError:
            return False


def default_badrpk_root() -> Path:
    """Return configured BADRPK repository collection root."""

    configured = os.getenv("BADRPK_REPOS_ROOT")

    if configured:
        return Path(configured).expanduser().resolve()

    candidate = Path.home() / "badrpk-repos"

    if candidate.is_dir():
        return candidate.resolve()

    return Path.home().resolve()


def canonical_target_name(name: str) -> str:
    """Resolve target names case-insensitively."""

    folded = str(name or "").strip().casefold()

    for candidate in BADRPK_REPOSITORY_NAMES:
        if candidate.casefold() == folded:
            return candidate

    raise ValueError(
        "Unknown BADRPK evolution target: "
        f"{name!r}. Expected one of: "
        + ", ".join(BADRPK_REPOSITORY_NAMES)
    )


def resolve_target(
    *,
    name: str,
    harness_repo: Path,
    explicit_repo: Path | None = None,
    badrpk_root: Path | None = None,
    require_exists: bool = True,
) -> TargetSpec:
    """Resolve one BADRPK target without changing engine behavior."""

    canonical = canonical_target_name(name)
    harness = Path(harness_repo).expanduser().resolve()

    if explicit_repo is not None:
        repo = Path(explicit_repo).expanduser().resolve()

    elif canonical == "sophyane":
        # Default Sophyane target must be the active development tree,
        # not a potentially stale sibling clone under ~/badrpk-repos.
        repo = harness

    else:
        root = (
            Path(badrpk_root).expanduser().resolve()
            if badrpk_root is not None
            else default_badrpk_root()
        )

        repo = (root / canonical).resolve()

    target = TargetSpec(
        name=canonical,
        repo=repo,
        harness_repo=harness,
    )

    if require_exists and not target.repo.is_dir():
        raise FileNotFoundError(
            f"BADRPK evolution target does not exist: "
            f"{target.name} -> {target.repo}"
        )

    if require_exists and not target.git_repo:
        raise ValueError(
            f"BADRPK evolution target is not a git repository: "
            f"{target.name} -> {target.repo}"
        )

    return target


def available_targets(
    *,
    harness_repo: Path,
    badrpk_root: Path | None = None,
) -> dict[str, TargetSpec]:
    """Return all currently resolvable BADRPK repositories."""

    harness = Path(harness_repo).expanduser().resolve()

    found: dict[str, TargetSpec] = {}

    for name in BADRPK_REPOSITORY_NAMES:
        try:
            target = resolve_target(
                name=name,
                harness_repo=harness,
                badrpk_root=badrpk_root,
                require_exists=True,
            )
        except (FileNotFoundError, ValueError):
            continue

        found[name] = target

    return found
