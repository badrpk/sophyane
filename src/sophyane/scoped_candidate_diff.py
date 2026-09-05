"""Bounded read-only diffs for explicitly selected repository paths."""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from sophyane.evolution.badrpk_targets import TargetSpec
from sophyane.evolution.target_worktree import (
    abandon_target_worktree,
    create_target_worktree,
)
from sophyane.recursive_evolution_controller import (
    RecursiveEvolutionError,
    resolve_candidate_path,
)

__all__ = [
    "ReconciliationResult",
    "candidate_diff_for_paths",
    "reconcile_candidate_paths",
]


def candidate_diff_for_paths(
    workspace: Path,
    paths: Iterable[str],
    *,
    max_files: int = 32,
    max_total_bytes: int = 2_000_000,
) -> str:
    """Return a deterministic diff containing only selected paths."""

    root = Path(workspace).expanduser().resolve()

    if (
        isinstance(max_files, bool)
        or not isinstance(max_files, int)
        or max_files < 1
    ):
        raise RecursiveEvolutionError(
            "max_files must be a positive integer"
        )

    if (
        isinstance(max_total_bytes, bool)
        or not isinstance(max_total_bytes, int)
        or max_total_bytes < 1
    ):
        raise RecursiveEvolutionError(
            "max_total_bytes must be a positive integer"
        )

    if isinstance(paths, (str, bytes)):
        raise RecursiveEvolutionError(
            "paths must be an iterable of relative paths"
        )

    try:
        supplied = tuple(paths)
    except Exception as error:
        raise RecursiveEvolutionError(
            "paths could not be enumerated"
        ) from error

    normalized: list[str] = []

    for raw in supplied:
        if not isinstance(raw, str) or not raw.strip():
            raise RecursiveEvolutionError(
                "selected paths must be non-empty strings"
            )

        lexical = Path(raw)

        if lexical.is_absolute() or ".." in lexical.parts:
            raise RecursiveEvolutionError(
                f"unsafe selected path: {raw}"
            )

        cursor = root

        for part in lexical.parts:
            if part in {"", "."}:
                continue

            cursor = cursor / part

            if cursor.is_symlink():
                raise RecursiveEvolutionError(
                    f"symlink selected path rejected: {raw}"
                )

        target = resolve_candidate_path(root, raw)
        relative = target.relative_to(root).as_posix()

        if not relative or relative == ".":
            raise RecursiveEvolutionError(
                f"invalid selected path: {raw}"
            )

        normalized.append(relative)

    selected = tuple(sorted(set(normalized)))

    if not selected:
        return ""

    if len(selected) > max_files:
        raise RecursiveEvolutionError(
            "selected path count exceeds max_files"
        )

    def git(*args: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ("git", "-C", str(root), *args),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    identity = git(
        "rev-parse",
        "--is-inside-work-tree",
    )

    if (
        identity.returncode != 0
        or identity.stdout.strip() != b"true"
    ):
        raise RecursiveEvolutionError(
            "workspace must be an existing Git repository"
        )

    head_before = git("rev-parse", "HEAD")
    status_before = git(
        "status",
        "--porcelain=v1",
        "-z",
    )

    if (
        head_before.returncode != 0
        or status_before.returncode != 0
    ):
        raise RecursiveEvolutionError(
            "unable to snapshot repository state"
        )

    parts: list[bytes] = []
    total = 0

    for relative in selected:
        encoded_relative = relative.encode(
            "utf-8",
            errors="surrogateescape",
        )
        indexed = git(
            "ls-files",
            "--stage",
            "--",
            relative,
        )

        if indexed.returncode != 0:
            raise RecursiveEvolutionError(
                "unable to inspect selected path: "
                + relative
            )

        exact_entries = []

        for line in indexed.stdout.splitlines():
            fields = line.split(b"\t", 1)

            if (
                len(fields) == 2
                and fields[1] == encoded_relative
            ):
                exact_entries.append(fields[0])

        if exact_entries:
            if any(
                entry.startswith(b"120000 ")
                for entry in exact_entries
            ):
                raise RecursiveEvolutionError(
                    "tracked symlink rejected: "
                    + relative
                )

            generated = git(
                "diff",
                "--no-ext-diff",
                "--binary",
                "--no-renames",
                "HEAD",
                "--",
                relative,
            )

            if generated.returncode != 0:
                raise RecursiveEvolutionError(
                    "unable to obtain tracked diff for "
                    + relative
                )

        else:
            ignored = git(
                "check-ignore",
                "-q",
                "--",
                relative,
            )

            if ignored.returncode == 0:
                raise RecursiveEvolutionError(
                    "ignored selected path rejected: "
                    + relative
                )

            if ignored.returncode != 1:
                raise RecursiveEvolutionError(
                    "unable to check ignore policy for "
                    + relative
                )

            target = root / relative

            if (
                not target.exists()
                or not target.is_file()
                or target.is_symlink()
            ):
                raise RecursiveEvolutionError(
                    "selected untracked path must be "
                    "a regular file: "
                    + relative
                )

            if target.stat().st_size > max_total_bytes:
                raise RecursiveEvolutionError(
                    "selected file exceeds byte budget: "
                    + relative
                )

            generated = git(
                "diff",
                "--no-ext-diff",
                "--binary",
                "--no-index",
                "--",
                "/dev/null",
                relative,
            )

            if generated.returncode not in {0, 1}:
                raise RecursiveEvolutionError(
                    "unable to obtain untracked diff for "
                    + relative
                )

        payload = generated.stdout.rstrip(b"\n")

        if not payload:
            continue

        projected = (
            total
            + len(payload)
            + (1 if parts else 0)
            + 1
        )

        if projected > max_total_bytes:
            raise RecursiveEvolutionError(
                "selected diff exceeds max_total_bytes"
            )

        parts.append(payload)
        total = projected

    head_after = git("rev-parse", "HEAD")
    status_after = git(
        "status",
        "--porcelain=v1",
        "-z",
    )

    if head_after.stdout != head_before.stdout:
        raise RecursiveEvolutionError(
            "repository HEAD changed during scoped diff"
        )

    if status_after.stdout != status_before.stdout:
        raise RecursiveEvolutionError(
            "repository status changed during scoped diff"
        )

    if not parts:
        return ""

    return (
        b"\n".join(parts) + b"\n"
    ).decode(
        "utf-8",
        errors="surrogateescape",
    )



@dataclass(frozen=True)
class ReconciliationResult:
    """Deterministic evidence from one non-destructive reconciliation."""

    source_head: str
    dirty_paths: tuple[str, ...]
    accepted_paths: tuple[str, ...]
    ephemeral_paths: tuple[str, ...]
    ephemeral_provenance: tuple[tuple[str, str], ...]
    unknown_paths: tuple[str, ...]
    reproduced_paths: tuple[str, ...]
    unrelated_paths: tuple[str, ...]
    authoritative_worktree_preserved: bool
    clean_integration_worktree: bool


def _git_bytes(
    repo: Path,
    *args: str,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ("git", "-C", str(repo), *args),
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _nul_paths(payload: bytes) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                raw.decode(
                    "utf-8",
                    errors="surrogateescape",
                )
                for raw in payload.split(b"\0")
                if raw
            }
        )
    )


def _dirty_paths(root: Path) -> tuple[str, ...]:
    tracked = _git_bytes(
        root,
        "diff",
        "--name-only",
        "-z",
        "HEAD",
        "--",
    )

    if tracked.returncode != 0:
        raise RecursiveEvolutionError(
            "unable to enumerate tracked dirty paths"
        )

    untracked = _git_bytes(
        root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
    )

    if untracked.returncode != 0:
        raise RecursiveEvolutionError(
            "unable to enumerate untracked paths"
        )

    return tuple(
        sorted(
            set(_nul_paths(tracked.stdout))
            | set(_nul_paths(untracked.stdout))
        )
    )


def _ephemeral_provenance(relative: str) -> str | None:
    """Return evidence for one exact, repository-owned ephemeral artifact."""
    path = Path(relative)
    name = path.name
    normalized = path.as_posix()

    if name.startswith(".sophyane-provider-response-") and name.endswith(".txt"):
        return "provider-response temporary artifact"
    if normalized == ".sophyane-candidate.patch":
        return "candidate-patch temporary artifact"
    if normalized in {
        "artifacts/sophyane-process-graph.json",
        "artifacts/sophyane-process-graph.mmd",
    }:
        return "Sophyane process-graph generated artifact"
    if normalized in {
        "website/static/artifacts/sophyane-visualization.json",
        "website/static/artifacts/sophyane-visualization.png",
    }:
        return "Sophyane visualization generated artifact"
    return None


def _known_ephemeral_path(relative: str) -> bool:
    """Return True only for narrow Sophyane-owned disposable names."""
    return _ephemeral_provenance(relative) is not None


def _worktree_changed_paths(root: Path) -> tuple[str, ...]:
    status = _git_bytes(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    )

    if status.returncode != 0:
        raise RecursiveEvolutionError(
            "unable to inspect reconciliation worktree"
        )

    paths: set[str] = set()

    records = status.stdout.split(b"\0")
    index = 0

    while index < len(records):
        record = records[index]

        if not record:
            index += 1
            continue

        if len(record) < 4:
            raise RecursiveEvolutionError(
                "malformed worktree status record"
            )

        code = record[:2]
        path = record[3:].decode(
            "utf-8",
            errors="surrogateescape",
        )

        paths.add(path)

        if (
            b"R" in code
            or b"C" in code
        ):
            index += 1

            if index < len(records) and records[index]:
                paths.add(
                    records[index].decode(
                        "utf-8",
                        errors="surrogateescape",
                    )
                )

        index += 1

    return tuple(sorted(paths))


def reconcile_candidate_paths(
    workspace: Path,
    accepted_paths: Iterable[str],
) -> ReconciliationResult:
    """Reproduce only accepted dirt in one detached clean worktree.

    The source repository's HEAD, index, tracked files and untracked files
    are preserved byte-for-byte at the Git status level. Unknown dirty work
    is classified but never deleted or copied into the verification worktree.
    """

    root = Path(workspace).expanduser().resolve()

    identity = _git_bytes(
        root,
        "rev-parse",
        "--is-inside-work-tree",
    )

    if (
        identity.returncode != 0
        or identity.stdout.strip() != b"true"
    ):
        raise RecursiveEvolutionError(
            "workspace must be an existing Git repository"
        )

    head_before = _git_bytes(
        root,
        "rev-parse",
        "HEAD",
    )

    status_before = _git_bytes(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    )

    if (
        head_before.returncode != 0
        or status_before.returncode != 0
    ):
        raise RecursiveEvolutionError(
            "unable to snapshot repository state"
        )

    try:
        supplied = tuple(accepted_paths)
    except Exception as error:
        raise RecursiveEvolutionError(
            "accepted paths could not be enumerated"
        ) from error

    if isinstance(accepted_paths, (str, bytes)):
        raise RecursiveEvolutionError(
            "accepted_paths must be an iterable of relative paths"
        )

    normalized: list[str] = []

    for raw in supplied:
        if not isinstance(raw, str) or not raw.strip():
            raise RecursiveEvolutionError(
                "accepted paths must be non-empty strings"
            )

        lexical = Path(raw)

        if lexical.is_absolute() or ".." in lexical.parts:
            raise RecursiveEvolutionError(
                f"unsafe accepted path: {raw}"
            )

        relative = lexical.as_posix().lstrip("./")

        if not relative or relative == ".":
            raise RecursiveEvolutionError(
                f"invalid accepted path: {raw}"
            )

        normalized.append(relative)

    accepted = tuple(sorted(set(normalized)))
    dirty = _dirty_paths(root)

    missing = tuple(
        path
        for path in accepted
        if path not in dirty
    )

    if missing:
        raise RecursiveEvolutionError(
            "accepted path is not currently dirty: "
            + ", ".join(missing)
        )

    accepted_set = set(accepted)

    ephemeral = tuple(
        path
        for path in dirty
        if (
            path not in accepted_set
            and _known_ephemeral_path(path)
        )
    )

    ephemeral_provenance = tuple(
        (path, _ephemeral_provenance(path) or "")
        for path in ephemeral
    )

    unknown = tuple(
        path
        for path in dirty
        if (
            path not in accepted_set
            and path not in set(ephemeral)
        )
    )

    patch = candidate_diff_for_paths(
        root,
        accepted,
    )

    if accepted and not patch:
        raise RecursiveEvolutionError(
            "accepted dirty paths produced an empty patch"
        )

    target = TargetSpec(
        name="sophyane",
        repo=root,
        harness_repo=root,
    )

    worktree = None
    reproduced: tuple[str, ...] = ()
    unrelated: tuple[str, ...] = ()
    clean = False

    with tempfile.TemporaryDirectory(
        prefix="sophyane-reconcile-",
    ) as temporary_root:
        try:
            worktree = create_target_worktree(
                target,
                root=Path(temporary_root),
            )

            initial = _worktree_changed_paths(
                worktree.path
            )

            if initial:
                raise RecursiveEvolutionError(
                    "new reconciliation worktree was not clean"
                )

            if patch:
                payload = patch.encode(
                    "utf-8",
                    errors="surrogateescape",
                )

                checked = _git_bytes(
                    worktree.path,
                    "apply",
                    "--check",
                    "--binary",
                    "-",
                    input_bytes=payload,
                )

                if checked.returncode != 0:
                    raise RecursiveEvolutionError(
                        "accepted patch does not apply to clean HEAD: "
                        + checked.stderr.decode(
                            "utf-8",
                            errors="replace",
                        ).strip()
                    )

                applied = _git_bytes(
                    worktree.path,
                    "apply",
                    "--binary",
                    "-",
                    input_bytes=payload,
                )

                if applied.returncode != 0:
                    raise RecursiveEvolutionError(
                        "accepted patch application failed: "
                        + applied.stderr.decode(
                            "utf-8",
                            errors="replace",
                        ).strip()
                    )

            reproduced = _worktree_changed_paths(
                worktree.path
            )

            unrelated = tuple(
                sorted(
                    set(reproduced)
                    - accepted_set
                )
            )

            missing_reproduced = tuple(
                sorted(
                    accepted_set
                    - set(reproduced)
                )
            )

            clean = (
                not unrelated
                and not missing_reproduced
                and set(reproduced) == accepted_set
            )

        finally:
            if worktree is not None:
                abandon_target_worktree(
                    worktree
                )

    head_after = _git_bytes(
        root,
        "rev-parse",
        "HEAD",
    )

    status_after = _git_bytes(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    )

    preserved = (
        head_after.returncode == 0
        and status_after.returncode == 0
        and head_after.stdout == head_before.stdout
        and status_after.stdout == status_before.stdout
    )

    if not preserved:
        raise RecursiveEvolutionError(
            "authoritative repository changed during reconciliation"
        )

    return ReconciliationResult(
        source_head=head_before.stdout.decode(
            "ascii",
            errors="strict",
        ).strip(),
        dirty_paths=dirty,
        accepted_paths=accepted,
        ephemeral_paths=ephemeral,
        ephemeral_provenance=ephemeral_provenance,
        unknown_paths=unknown,
        reproduced_paths=reproduced,
        unrelated_paths=unrelated,
        authoritative_worktree_preserved=True,
        clean_integration_worktree=clean,
    )
