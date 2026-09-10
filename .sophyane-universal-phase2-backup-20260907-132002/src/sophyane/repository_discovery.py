"""Generic local repository discovery and task-relevance ranking.

This module is deliberately domain agnostic.  It discovers accessible local
Git repositories and ranks them against arbitrary task text.  Discovery is
read-only and never mutates sibling repositories.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
import subprocess
from typing import Iterable


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+\-]{1,63}")
_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    ".next",
    ".cache",
}


@dataclass(frozen=True)
class RepositoryCandidate:
    path: Path
    remote: str
    owner: str
    name: str
    score: float
    evidence: tuple[str, ...]


def _git(path: Path, *args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), *args],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).strip()
    except Exception:
        return ""


def _remote_identity(remote: str) -> tuple[str, str] | None:
    value = remote.strip().rstrip("/")

    patterns = (
        r"github\.com[:/](?P<owner>[^/]+)/(?P<name>[^/]+?)(?:\.git)?$",
        r"/(?P<owner>[^/]+)/(?P<name>[^/]+?)(?:\.git)?$",
    )

    for pattern in patterns:
        match = re.search(pattern, value, re.I)
        if match:
            return (
                match.group("owner"),
                re.sub(r"\.git$", "", match.group("name"), flags=re.I),
            )

    return None


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in _TOKEN_RE.findall(text or "")
        if len(token) >= 3
    }


def discover_local_repositories(
    roots: Iterable[Path] | None = None,
    *,
    owner: str | None = None,
) -> list[tuple[Path, str, str, str]]:
    """Discover local Git repositories belonging to the configured owner."""

    configured_owner = (
        owner
        or os.environ.get("SOPHYANE_REPO_OWNER")
        or "badrpk"
    ).lower()

    search_roots = list(roots or (Path.home(),))
    found: list[tuple[Path, str, str, str]] = []
    seen: set[Path] = set()

    for root in search_roots:
        root = root.expanduser().resolve()

        if not root.exists():
            continue

        candidates = [root]

        try:
            candidates.extend(
                child
                for child in root.iterdir()
                if child.is_dir()
            )
        except OSError:
            continue

        for path in candidates:
            try:
                resolved = path.resolve()
            except OSError:
                continue

            if resolved in seen:
                continue

            seen.add(resolved)

            if not (resolved / ".git").exists():
                continue

            remote = _git(resolved, "remote", "get-url", "origin")
            identity = _remote_identity(remote)

            if not identity:
                continue

            repo_owner, repo_name = identity

            if repo_owner.lower() != configured_owner:
                continue

            found.append(
                (
                    resolved,
                    remote,
                    repo_owner,
                    repo_name,
                )
            )

    return found


def _metadata_text(repo: Path, name: str) -> str:
    parts = [name, repo.name]

    for filename in (
        "README.md",
        "README.rst",
        "README.txt",
        "pyproject.toml",
        "package.json",
        "setup.py",
        "Cargo.toml",
        "go.mod",
    ):
        path = repo / filename

        if not path.is_file():
            continue

        try:
            parts.append(
                path.read_text(
                    errors="ignore",
                )[:20000]
            )
        except OSError:
            pass

    return "\n".join(parts)


def _filename_tokens(repo: Path, limit: int = 500) -> set[str]:
    values: set[str] = set()
    count = 0

    try:
        iterator = repo.rglob("*")
    except OSError:
        return values

    for path in iterator:
        if count >= limit:
            break

        try:
            rel = path.relative_to(repo)
        except ValueError:
            continue

        if any(part in _SKIP_DIRS for part in rel.parts):
            continue

        if not path.is_file():
            continue

        count += 1
        values.update(_tokens(str(rel)))

    return values


def rank_repositories(
    request: str,
    *,
    roots: Iterable[Path] | None = None,
    owner: str | None = None,
    limit: int = 8,
) -> list[RepositoryCandidate]:
    """Rank discovered repositories against arbitrary request semantics."""

    request_tokens = _tokens(request)

    results: list[RepositoryCandidate] = []

    for path, remote, repo_owner, repo_name in discover_local_repositories(
        roots,
        owner=owner,
    ):
        metadata_tokens = _tokens(
            _metadata_text(
                path,
                repo_name,
            )
        )
        file_tokens = _filename_tokens(path)

        metadata_overlap = request_tokens & metadata_tokens
        filename_overlap = request_tokens & file_tokens

        score = (
            float(len(metadata_overlap) * 3)
            + float(len(filename_overlap))
        )

        evidence: list[str] = []

        if metadata_overlap:
            evidence.append(
                "metadata:"
                + ",".join(sorted(metadata_overlap)[:12])
            )

        if filename_overlap:
            evidence.append(
                "files:"
                + ",".join(sorted(filename_overlap)[:12])
            )

        # Sophyane itself remains available even when lexical similarity
        # is low because it is the execution harness, not a domain shortcut.
        if path.resolve() == Path.cwd().resolve():
            score += 0.25
            evidence.append("active-workspace")

        results.append(
            RepositoryCandidate(
                path=path,
                remote=remote,
                owner=repo_owner,
                name=repo_name,
                score=score,
                evidence=tuple(evidence),
            )
        )

    results.sort(
        key=lambda item: (
            -item.score,
            item.name.lower(),
        )
    )

    return results[: max(1, int(limit))]


def repository_context(
    request: str,
    *,
    limit: int = 5,
) -> str:
    """Return compact read-only repository evidence for provider context."""

    candidates = rank_repositories(
        request,
        limit=limit,
    )

    if not candidates:
        return ""

    lines = [
        "Available related repositories (read-only discovery):"
    ]

    for item in candidates:
        evidence = "; ".join(item.evidence) or "discovered"
        lines.append(
            f"- {item.owner}/{item.name}: "
            f"{item.path} "
            f"[score={item.score:.2f}; {evidence}]"
        )

    return "\n".join(lines)
