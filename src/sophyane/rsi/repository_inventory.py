"""Persistent inventory and round-robin cursor for configured repositories."""

from __future__ import annotations

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


def _test_commands(path: Path) -> tuple[tuple[str, ...], ...]:
    python_markers = ("pyproject.toml", "pytest.ini", "setup.cfg")
    if any((path / name).exists() for name in python_markers) or (path / "tests").is_dir():
        return (("python", "-m", "pytest", "-q"),)
    if (path / "package.json").is_file():
        return (("npm", "test"),)
    if (path / "Cargo.toml").is_file():
        return (("cargo", "test"),)
    if (path / "go.mod").is_file():
        return (("go", "test", "./..."),)
    return ()


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
                    }
                )
            )
        self.records = tuple(records)
        cursor = data.get("cursor", {})
        ids = {record.repo_id for record in self.records}
        self.cursor = RepositoryCursor(
            next_index=int(cursor.get("next_index", 0)),
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

    def refresh(self) -> tuple[RepositoryRecord, ...]:
        records = []
        for path, remote, owner, name in discover_local_repositories(
            self.roots, owner=self.owner, prefer_cwd=False,
        ):
            path = path.resolve()
            if not _within_roots(path, self.roots):
                continue
            commit = _git(path, "rev-parse", "HEAD")
            if not commit:
                continue
            branch = _git(path, "branch", "--show-current")
            tests = _test_commands(path)
            editable = tuple(
                name
                for name in ("src", "tests")
                if (path / name).is_dir() and not (path / name).is_symlink()
            )
            repo_id = f"{owner.lower()}/{name.lower()}"
            identity = {
                "repo_id": repo_id,
                "path": str(path),
                "remote": remote,
                "owner": owner,
                "name": name,
                "commit": commit,
                "branch": branch,
                "test_commands": tests,
                "editable_paths": editable,
            }
            digest = hashlib.sha256(
                json.dumps(identity, sort_keys=True).encode()
            ).hexdigest()
            records.append(RepositoryRecord(**identity, digest=digest))
        self.records = tuple(sorted(records, key=lambda record: (record.repo_id, record.path)))
        ids = {record.repo_id for record in self.records}
        self.cursor.scanned_commits = {
            key: value
            for key, value in self.cursor.scanned_commits.items()
            if key in ids
        }
        self.cursor.next_index = self.cursor.next_index % len(self.records) if self.records else 0
        self._save()
        return self.records

    def next_repository(self) -> RepositoryRecord | None:
        self.refresh()
        if not self.records:
            return None
        index = self.cursor.next_index
        record = self.records[index]
        self.cursor.next_index = (index + 1) % len(self.records)
        self.cursor.scanned_commits[record.repo_id] = record.commit
        self._save()
        return record
