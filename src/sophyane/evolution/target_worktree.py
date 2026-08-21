"""Isolated git worktrees for BADRPK evolution targets.

V2B provides lifecycle primitives only.

Creating a target worktree does not redirect EvolutionEngine.repo,
does not patch the target, does not commit, and does not promote.
"""

from __future__ import annotations

import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from .badrpk_targets import TargetSpec


@dataclass(frozen=True)
class TargetWorktree:
    """One detached isolated target worktree."""

    target: TargetSpec
    path: Path
    source_head: str

    @property
    def exists(self) -> bool:
        return self.path.is_dir()


def default_worktree_root() -> Path:
    """Return Sophyane's disposable cross-repository worktree root."""

    return (
        Path.home()
        / ".cache"
        / "sophyane"
        / "evolution-target-worktrees"
    )


def _git(
    repo: Path,
    *args: str,
    capture: bool = False,
) -> str:
    completed = subprocess.run(
        (
            "git",
            "-C",
            str(repo),
            *args,
        ),
        check=True,
        text=True,
        stdout=(
            subprocess.PIPE
            if capture
            else None
        ),
        stderr=(
            subprocess.PIPE
            if capture
            else None
        ),
    )

    return (
        completed.stdout.strip()
        if capture
        else ""
    )


def target_head(target: TargetSpec) -> str:
    """Return current target HEAD without changing it."""

    return _git(
        target.repo,
        "rev-parse",
        "HEAD",
        capture=True,
    )


def create_target_worktree(
    target: TargetSpec,
    *,
    root: Path | None = None,
) -> TargetWorktree:
    """Create a detached worktree at the target's current HEAD."""

    if not target.git_repo:
        raise ValueError(
            f"Target is not a git repository: {target.repo}"
        )

    source_head = target_head(target)

    worktree_root = (
        Path(root).expanduser().resolve()
        if root is not None
        else default_worktree_root().resolve()
    )

    worktree_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    token = uuid.uuid4().hex[:12]

    path = (
        worktree_root
        / f"{target.name}-{source_head[:12]}-{token}"
    )

    if path.exists():
        raise FileExistsError(path)

    _git(
        target.repo,
        "worktree",
        "add",
        "--detach",
        str(path),
        source_head,
    )

    if not path.is_dir():
        raise RuntimeError(
            f"git reported success but worktree is absent: {path}"
        )

    worktree_head = _git(
        path,
        "rev-parse",
        "HEAD",
        capture=True,
    )

    if worktree_head != source_head:
        raise RuntimeError(
            "Target worktree HEAD mismatch: "
            f"{worktree_head} != {source_head}"
        )

    return TargetWorktree(
        target=target,
        path=path,
        source_head=source_head,
    )


def remove_target_worktree(
    worktree: TargetWorktree,
) -> None:
    """Remove a clean disposable target worktree."""

    if worktree.path.exists():
        _git(
            worktree.target.repo,
            "worktree",
            "remove",
            str(worktree.path),
        )

    _git(
        worktree.target.repo,
        "worktree",
        "prune",
    )

    # A failed external git cleanup should never leave arbitrary
    # directory deletion hidden inside this function. Only remove an
    # empty leftover directory.
    if worktree.path.exists():
        try:
            worktree.path.rmdir()
        except OSError as error:
            raise RuntimeError(
                "Target worktree still contains files after "
                f"git worktree remove: {worktree.path}"
            ) from error


def abandon_target_worktree(
    worktree: TargetWorktree,
) -> None:
    """Explicitly discard a disposable worktree, including modifications.

    This is intentionally separate from remove_target_worktree so normal
    cleanup never silently destroys edits.
    """

    _git(
        worktree.target.repo,
        "worktree",
        "remove",
        "--force",
        str(worktree.path),
    )

    _git(
        worktree.target.repo,
        "worktree",
        "prune",
    )

    if worktree.path.exists():
        shutil.rmtree(worktree.path)
