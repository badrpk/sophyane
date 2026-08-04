"""Repository revision manifests and browser-entry prefiltering.

The module prevents unchanged source trees from being fully rescanned and
prevents browser acquisition from ingesting repositories that contain no
materializable browser entry point.

Downloaded code is inspected as text only and is never executed.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time

from pathlib import Path
from typing import Any, Callable, Iterable


Progress = Callable[[str], None]

MEMORY = (
    Path.home()
    / ".local/share/sophyane/code_memory"
)

MANIFEST_DIR = (
    MEMORY
    / "repository_manifests"
)

MANIFEST_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


IGNORED_PARTS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "coverage",
    ".next",
    ".nuxt",
    "target",
    "venv",
    ".venv",
}


SOURCE_SUFFIXES = {
    ".py",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".htm",
    ".css",
    ".scss",
    ".sass",
    ".less",
    ".vue",
    ".svelte",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".md",
    ".rs",
    ".go",
    ".java",
    ".kt",
    ".kts",
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".hpp",
    ".cs",
    ".rb",
    ".php",
    ".swift",
}


BROWSER_ENTRY_NAMES = {
    "index.html",
    "index.htm",
    "app.html",
    "game.html",
    "demo.html",
    "main.html",
}


def _progress(
    callback: Progress | None,
) -> Progress:
    return callback or (
        lambda _message: None
    )


def _inside_ignored_path(
    path: Path,
) -> bool:
    return any(
        part.lower() in IGNORED_PARTS
        for part in path.parts
    )


def _safe_git(
    root: Path,
    *args: str,
) -> str | None:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                *args,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (
        OSError,
        subprocess.SubprocessError,
    ):
        return None

    if result.returncode != 0:
        return None

    value = result.stdout.strip()

    return value or None


def git_revision(
    root: Path,
) -> str | None:
    """Return HEAD plus a bounded dirty-worktree fingerprint."""

    root = Path(root).expanduser().resolve()

    head = _safe_git(
        root,
        "rev-parse",
        "HEAD",
    )

    if not head:
        return None

    dirty = _safe_git(
        root,
        "status",
        "--porcelain=v1",
        "--untracked-files=no",
    ) or ""

    dirty_hash = hashlib.blake2b(
        dirty.encode(
            "utf-8",
            errors="ignore",
        ),
        digest_size=12,
    ).hexdigest()

    return (
        "git:"
        + head
        + ":"
        + dirty_hash
    )


def iter_source_files(
    root: Path,
    *,
    maximum: int = 25_000,
) -> Iterable[Path]:
    root = Path(root).expanduser().resolve()
    count = 0

    for path in root.rglob("*"):
        if count >= maximum:
            break

        if not path.is_file():
            continue

        try:
            relative = path.relative_to(root)
        except ValueError:
            continue

        if _inside_ignored_path(relative):
            continue

        if path.suffix.lower() not in SOURCE_SUFFIXES:
            continue

        count += 1
        yield path


def tree_revision(
    root: Path,
    *,
    maximum_files: int = 25_000,
) -> str:
    """Create a lightweight revision from path, size and nanosecond mtime."""

    root = Path(root).expanduser().resolve()
    digest = hashlib.blake2b(
        digest_size=20,
    )

    files = []

    for path in iter_source_files(
        root,
        maximum=maximum_files,
    ):
        try:
            stat = path.stat()
            relative = path.relative_to(root)
        except OSError:
            continue

        files.append(
            (
                str(relative),
                int(stat.st_size),
                int(stat.st_mtime_ns),
            )
        )

    for relative, size, modified in sorted(files):
        digest.update(
            relative.encode(
                "utf-8",
                errors="ignore",
            )
        )

        digest.update(
            b"\0"
        )

        digest.update(
            str(size).encode()
        )

        digest.update(
            b"\0"
        )

        digest.update(
            str(modified).encode()
        )

        digest.update(
            b"\n"
        )

    return (
        "tree:"
        + digest.hexdigest()
        + ":"
        + str(len(files))
    )


def repository_revision(
    root: Path,
) -> str:
    return (
        git_revision(root)
        or tree_revision(root)
    )


def manifest_key(
    root: Path,
    source: str,
) -> str:
    payload = (
        str(
            Path(root)
            .expanduser()
            .resolve()
        )
        + "\n"
        + str(source)
    )

    return hashlib.sha256(
        payload.encode(
            "utf-8",
            errors="ignore",
        )
    ).hexdigest()


def manifest_path(
    root: Path,
    source: str,
) -> Path:
    key = manifest_key(
        root,
        source,
    )

    return (
        MANIFEST_DIR
        / key[:2]
        / (
            key
            + ".json"
        )
    )


def load_manifest(
    root: Path,
    source: str,
) -> dict[str, Any] | None:
    path = manifest_path(
        root,
        source,
    )

    if not path.is_file():
        return None

    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8",
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ):
        return None

    return (
        payload
        if isinstance(payload, dict)
        else None
    )


def atomic_write_json(
    path: Path,
    payload: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    descriptor, temporary_name = (
        tempfile.mkstemp(
            prefix=(
                path.name
                + "."
            ),
            suffix=".tmp",
            dir=str(path.parent),
        )
    )

    temporary = Path(
        temporary_name
    )

    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
        ) as handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )

            handle.write(
                "\n"
            )

            handle.flush()
            os.fsync(
                handle.fileno()
            )

        os.replace(
            temporary,
            path,
        )

    finally:
        temporary.unlink(
            missing_ok=True,
        )


def should_skip_revision(
    root: Path,
    *,
    source: str,
    revision: str,
    limit_files: int,
    limit_chunks: int,
) -> tuple[bool, str]:
    manifest = load_manifest(
        root,
        source,
    )

    if not manifest:
        return (
            False,
            "no previous manifest",
        )

    if manifest.get(
        "revision"
    ) != revision:
        return (
            False,
            "repository revision changed",
        )

    if int(
        manifest.get(
            "limit_files",
            -1,
        )
    ) != int(limit_files):
        return (
            False,
            "file limit changed",
        )

    if int(
        manifest.get(
            "limit_chunks",
            -1,
        )
    ) != int(limit_chunks):
        return (
            False,
            "chunk limit changed",
        )

    if not bool(
        manifest.get(
            "completed",
            False,
        )
    ):
        return (
            False,
            "previous scan incomplete",
        )

    return (
        True,
        "unchanged revision already indexed",
    )


def record_manifest(
    root: Path,
    *,
    source: str,
    revision: str,
    limit_files: int,
    limit_chunks: int,
    report: dict[str, Any],
) -> Path:
    payload = {
        "root":
            str(
                Path(root)
                .expanduser()
                .resolve()
            ),

        "source":
            str(source),

        "revision":
            str(revision),

        "limit_files":
            int(limit_files),

        "limit_chunks":
            int(limit_chunks),

        "completed":
            True,

        "files_scanned":
            int(
                report.get(
                    "files_scanned",
                    0,
                )
                or 0
            ),

        "chunks_added":
            int(
                report.get(
                    "chunks_added",
                    0,
                )
                or 0
            ),

        "skipped_dupes":
            int(
                report.get(
                    "skipped_dupes",
                    0,
                )
                or 0
            ),

        "memory_size":
            int(
                report.get(
                    "memory_size",
                    0,
                )
                or 0
            ),

        "recorded_at":
            time.time(),
    }

    path = manifest_path(
        root,
        source,
    )

    atomic_write_json(
        path,
        payload,
    )

    return path


def unchanged_report(
    root: Path,
    *,
    revision: str,
    memory_size: int,
    reason: str,
) -> dict[str, Any]:
    return {
        "root":
            str(
                Path(root)
                .expanduser()
                .resolve()
            ),

        "files_scanned":
            0,

        "chunks_added":
            0,

        "skipped_dupes":
            0,

        "memory_size":
            int(memory_size),

        "revision":
            revision,

        "manifest_skip":
            True,

        "skip_reason":
            reason,

        "ts":
            time.time(),
    }


def browser_entry_files(
    root: Path,
    *,
    maximum: int = 200,
) -> list[Path]:
    """Return browser HTML entry points, excluding docs/tests/vendor output."""

    root = Path(root).expanduser().resolve()
    candidates: list[Path] = []

    excluded = (
        IGNORED_PARTS
        | {
            "docs",
            "doc",
            "test",
            "tests",
            "spec",
            "specs",
            "examples",
            "fixtures",
        }
    )

    for path in root.rglob("*"):
        if len(candidates) >= maximum:
            break

        if not path.is_file():
            continue

        if path.suffix.lower() not in {
            ".html",
            ".htm",
        }:
            continue

        try:
            relative = path.relative_to(
                root
            )
        except ValueError:
            continue

        lowered_parts = {
            part.lower()
            for part in relative.parts[:-1]
        }

        if lowered_parts & excluded:
            continue

        name = path.name.lower()

        # Prefer conventional entries, but retain substantive standalone HTML.
        if (
            name in BROWSER_ENTRY_NAMES
            or path.stat().st_size >= 500
        ):
            candidates.append(
                path
            )

    return sorted(
        candidates,
        key=lambda item: (
            0
            if item.name.lower()
            in BROWSER_ENTRY_NAMES
            else 1,
            len(
                item.relative_to(root).parts
            ),
            str(item).lower(),
        ),
    )


def is_browser_acquisition_source(
    source: str,
) -> bool:
    low = str(
        source or ""
    ).lower()

    return (
        low.startswith(
            "internet:"
        )
        or "browser" in low
        or "web-acquire" in low
    )


def browser_prefilter_report(
    root: Path,
    *,
    source: str,
    memory_size: int,
) -> dict[str, Any] | None:
    if not is_browser_acquisition_source(
        source
    ):
        return None

    entries = browser_entry_files(
        root
    )

    if entries:
        return None

    return {
        "root":
            str(
                Path(root)
                .expanduser()
                .resolve()
            ),

        "files_scanned":
            0,

        "chunks_added":
            0,

        "skipped_dupes":
            0,

        "memory_size":
            int(memory_size),

        "browser_prefilter_skip":
            True,

        "skip_reason":
            "no materializable browser HTML entry point",

        "browser_entries":
            0,

        "ts":
            time.time(),
    }


__all__ = [
    "browser_entry_files",
    "browser_prefilter_report",
    "record_manifest",
    "repository_revision",
    "should_skip_revision",
    "tree_revision",
    "unchanged_report",
]
