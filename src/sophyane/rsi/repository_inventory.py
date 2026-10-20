"""Persistent inventory and round-robin cursor for configured repositories."""

from __future__ import annotations

from bisect import bisect_left
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Iterable

from sophyane.repository_discovery import discover_local_repositories


@dataclass(frozen=True)
class RepositoryRecord:
    repo_id: str
    path: str
    remote: str
    owner: str
    name: str
    commit: str
    branch: str
    test_commands: tuple[tuple[str, ...], ...]
    editable_paths: tuple[str, ...]
    digest: str
    language: str = "unknown"
    default_branch: str = ""


@dataclass
class RepositoryCursor:
    next_index: int = 0
    scanned_commits: dict[str, str] = field(default_factory=dict)


def _git(path: Path, *args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), *args],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _within_roots(path: Path, roots: tuple[Path, ...]) -> bool:
    resolved = path.resolve()
    return any(resolved.is_relative_to(root) for root in roots)


def _rebase_index(
    previous_ids: tuple[str, ...], next_index: int, current_ids: tuple[str, ...]
) -> int:
    if not previous_ids or not current_ids:
        return 0
    next_id = previous_ids[next_index % len(previous_ids)]
    position = bisect_left(current_ids, next_id)
    return position % len(current_ids)


def _language(path: Path) -> str:
    try:
        names = {entry.name for entry in os.scandir(path)}
    except OSError:
        names = set()
    for marker, language in (
        ("go.mod", "go"),
        ("Cargo.toml", "rust"),
        ("package.json", "javascript"),
        ("pyproject.toml", "python"),
        ("pytest.ini", "python"),
        ("setup.cfg", "python"),
    ):
        if marker in names and (path / marker).is_file():
            return language
    if "tests" in names and "src" in names and (path / "tests").is_dir() and (path / "src").is_dir():
        return "python"
    return "unknown"


def _test_commands(language: str) -> tuple[tuple[str, ...], ...]:
    commands = {
        "python": (("python", "-m", "pytest", "-q"),),
        "javascript": (("npm", "test"),),
        "rust": (("cargo", "test"),),
        "go": (("go", "test", "./..."),),
    }
    return commands.get(language, ())


def _default_branch(path: Path, current: str) -> str:
    refs = path / ".git" / "refs" / "heads"
    for name in ("main", "master"):
        if (refs / name).is_file():
            return name
    remote_head = _git(
        path, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"
    )
    if remote_head.startswith("origin/"):
        return remote_head.removeprefix("origin/")
    for name in ("main", "master"):
        if _git(path, "show-ref", "--verify", f"refs/heads/{name}"):
            return name
    return current


def _editable_paths(path: Path, language: str) -> tuple[str, ...]:
    rules = {
        "python": (
            ("src", "tests"),
            {".py"},
            {"pyproject.toml", "setup.cfg", "pytest.ini"},
        ),
        "javascript": (
            ("src", "app", "pages", "test", "tests"),
            {".js", ".jsx", ".ts", ".tsx"},
            {"package.json", "tsconfig.json", "vite.config.js", "vite.config.ts"},
        ),
        "rust": (
            ("src", "tests", "benches", "examples"),
            {".rs"},
            {"Cargo.toml", "build.rs"},
        ),
        "go": (("cmd", "internal", "pkg", "test", "tests"), {".go"}, {"go.mod", "go.sum"}),
    }
    directories, suffixes, files = rules.get(language, (("src", "tests"), set(), set()))
    try:
        entries = {entry.name: entry for entry in os.scandir(path)}
    except OSError:
        entries = {}
    editable = [
        name
        for name in directories
        if name in entries and entries[name].is_dir(follow_symlinks=False)
    ]
    root_files = sorted(
        name
        for name, child in entries.items()
        if child.is_file(follow_symlinks=False)
        and (Path(name).suffix in suffixes or name in files)
    )
    editable.extend(root_files[:64])
    return tuple(editable)


class RepositoryInventory:
    def __init__(
        self,
        state_path: Path,
        *,
        roots: Iterable[Path] | None = None,
        owner: str | None = None,
    ) -> None:
        self.state_path = Path(state_path)
        if roots is None:
            configured = os.environ.get("SOPHYANE_REPOSITORY_ROOTS", "")
            roots = (
                Path(item).expanduser()
                for item in configured.split(os.pathsep)
                if item.strip()
            )
        self.roots = tuple(Path(root).expanduser().resolve() for root in roots)
        self.owner = (owner or os.environ.get("SOPHYANE_REPO_OWNER") or "badrpk").lower()
        self.records: tuple[RepositoryRecord, ...] = ()
        self.cursor = RepositoryCursor()
        if self.state_path.exists():
            self._load()

    def _load(self) -> None:
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        previous_ids = tuple(item["repo_id"] for item in data.get("records", []))
        records = []
        for item in data.get("records", []):
            path = Path(item["path"])
            if not _within_roots(path, self.roots) or not (path / ".git").exists():
                continue
            records.append(
                RepositoryRecord(
                    **{
                        **item,
                        "test_commands": tuple(
                            tuple(command) for command in item["test_commands"]
                        ),
                        "editable_paths": tuple(item["editable_paths"]),
                        "language": item.get("language", "unknown"),
                        "default_branch": item.get("default_branch", item["branch"]),
                    }
                )
            )
        self.records = tuple(sorted(records, key=lambda record: (record.repo_id, record.path)))
        cursor = data.get("cursor", {})
        ids = {record.repo_id for record in self.records}
        self.cursor = RepositoryCursor(
            next_index=_rebase_index(
                previous_ids,
                int(cursor.get("next_index", 0)),
                tuple(record.repo_id for record in self.records),
            ),
            scanned_commits={
                key: value
                for key, value in cursor.get("scanned_commits", {}).items()
                if key in ids
            },
        )

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "records": [asdict(record) for record in self.records],
                "cursor": asdict(self.cursor),
            },
            sort_keys=True,
            indent=2,
        ) + "\n"
        fd, temporary = tempfile.mkstemp(
            prefix=f".{self.state_path.name}.", dir=self.state_path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.state_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def refresh(self, *, workers: int | None = None) -> tuple[RepositoryRecord, ...]:
        previous_ids = tuple(record.repo_id for record in self.records)
        next_index = self.cursor.next_index
        if workers is None:
            workers = int(os.environ.get("SOPHYANE_RSI_SCAN_WORKERS", "8"))
        if workers < 1:
            raise ValueError("repository scan workers must be positive")
        workers = min(int(workers), 32)

        def inspect(item: tuple[Path, str, str, str]) -> RepositoryRecord | None:
            path, remote, owner, name = item
            path = path.resolve()
            if not _within_roots(path, self.roots):
                return None
            commit = _git(path, "rev-parse", "HEAD")
            if not commit:
                return None
            branch = _git(path, "branch", "--show-current")
            language = _language(path)
            default_branch = _default_branch(path, branch)
            tests = _test_commands(language)
            editable = _editable_paths(path, language)
            repo_id = f"{owner.lower()}/{name.lower()}"
            identity = {
                "repo_id": repo_id,
                "path": str(path),
                "remote": remote,
                "owner": owner,
                "name": name,
                "commit": commit,
                "branch": branch,
                "language": language,
                "default_branch": default_branch,
                "test_commands": tests,
                "editable_paths": editable,
            }
            digest = hashlib.sha256(
                json.dumps(identity, sort_keys=True).encode()
            ).hexdigest()
            return RepositoryRecord(**identity, digest=digest)

        discovered = discover_local_repositories(
            self.roots, owner=self.owner, prefer_cwd=False,
        )
        if workers == 1:
            records = [record for item in discovered if (record := inspect(item)) is not None]
        else:
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="sophyane-inventory") as pool:
                records = [record for record in pool.map(inspect, discovered) if record is not None]
        self.records = tuple(sorted(records, key=lambda record: (record.repo_id, record.path)))
        ids = {record.repo_id for record in self.records}
        self.cursor.scanned_commits = {
            key: value
            for key, value in self.cursor.scanned_commits.items()
            if key in ids
        }
        self.cursor.next_index = _rebase_index(
            previous_ids, next_index, tuple(record.repo_id for record in self.records)
        )
        self._save()
        return self.records

    def next_repository(self) -> RepositoryRecord | None:
        self.refresh()
        for offset in range(len(self.records)):
            record = self.records[(self.cursor.next_index + offset) % len(self.records)]
            if self.cursor.scanned_commits.get(record.repo_id) != record.commit:
                return record
        return None

    def complete_scan(self, record: RepositoryRecord) -> None:
        """Advance only after the caller has durably recorded the scan outcome."""
        selected = self.next_repository()
        if selected is None or (selected.repo_id, selected.commit) != (record.repo_id, record.commit):
            raise ValueError("scan selection is stale or already completed")
        index = self.records.index(selected)
        self.cursor.next_index = (index + 1) % len(self.records)
        self.cursor.scanned_commits[selected.repo_id] = selected.commit
        self._save()
