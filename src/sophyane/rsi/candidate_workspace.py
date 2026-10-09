"""Owned filesystem candidate snapshots; never a primary-tree transaction."""
from dataclasses import dataclass
from pathlib import Path
import difflib
import hashlib
import os
import tempfile

from .authority import Operation, require

_EXCLUDED = {".git", ".venv", "__pycache__", ".pytest_cache", "node_modules"}
_IMMUTABLE_RSI_TRUST_ROOTS = frozenset({
    "src/sophyane/intelligence_authority.py",
    "src/sophyane/rsi_host_broker.py",
})


@dataclass(frozen=True)
class CandidateSnapshot:
    fingerprint: str
    files: dict[str, bytes]


@dataclass(frozen=True)
class CandidateDiff:
    fingerprint: str
    changed_files: tuple[str, ...]
    text: str
    growth: int


def snapshot(path, *, max_bytes=64 * 1024**2, max_files=10000):
    path = Path(path)
    files, size = {}, 0
    for directory, dirs, names in os.walk(path, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in _EXCLUDED)
        for name in (*dirs, *sorted(names)):
            target = Path(directory) / name
            if target.is_symlink():
                raise PermissionError("Linked snapshot paths are forbidden")
        for name in sorted(names):
            target = Path(directory) / name
            if not target.is_file():
                raise PermissionError("Nonregular snapshot file")
            size += target.stat().st_size
            if size > max_bytes or len(files) >= max_files:
                raise ValueError("Snapshot budget exceeded")
            files[target.relative_to(path).as_posix()] = target.read_bytes()
    digest = hashlib.sha256()
    for name, value in sorted(files.items()):
        digest.update(name.encode() + b"\0" + hashlib.sha256(value).digest())
    return CandidateSnapshot(digest.hexdigest(), files)


class CandidateWorkspace:
    def __init__(self, repository, root):
        self.repository, self.root = Path(repository).resolve(), Path(root).resolve()
        self._owned = None
        self.path = None
        self._promoted = None
        self._accepted = False

    def create(self):
        if self.root.is_relative_to(self.repository):
            raise PermissionError("Candidate root must be outside primary tree")
        self.baseline = snapshot(self.repository)
        self.root.mkdir(parents=True, exist_ok=True)
        self._owned = tempfile.TemporaryDirectory(prefix="rsi-", dir=self.root)
        self.path = Path(self._owned.name)
        for name, value in self.baseline.files.items():
            target = self.path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value)
        return self

    def apply(self, provider, files, allowed_paths):
        require(provider, Operation.SOPHYANE_SOURCE_MUTATION)
        self._replace_data(files, allowed_paths)

    def preview(self, files, allowed_paths):
        self._replace_data(files, allowed_paths)

    def _replace_data(self, files, allowed_paths):
        if not self._owned or not self.path or self.path == self.repository:
            raise PermissionError("Owned isolated snapshot required")
        targets = []
        for name, content in files.items():
            relative = Path(name)
            if (name not in allowed_paths or relative.is_absolute() or ".." in relative.parts
                    or any(part in _EXCLUDED for part in relative.parts)
                    or not isinstance(content, str)):
                raise PermissionError("Unauthorized replacement path")
            if relative.as_posix() in _IMMUTABLE_RSI_TRUST_ROOTS:
                raise PermissionError("Immutable RSI trust root")
            target = self.path / relative
            if not target.resolve().is_relative_to(self.path):
                raise PermissionError("Replacement escapes candidate")
            for item in (target, *target.parents):
                if item == self.path:
                    break
                if item.is_symlink() or (item.is_file() and item.stat().st_nlink > 1):
                    raise PermissionError("Linked replacement")
            targets.append((target, content))
        for target, content in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)

    def diff(self):
        current = snapshot(self.path)
        names = tuple(sorted(name for name in set(current.files) | set(self.baseline.files)
                             if current.files.get(name) != self.baseline.files.get(name)))
        text, growth = [], 0
        for name in names:
            old, new = self.baseline.files.get(name, b""), current.files.get(name, b"")
            growth += len(new) - len(old)
            text.extend(difflib.unified_diff(
                old.decode("utf8", "replace").splitlines(True),
                new.decode("utf8", "replace").splitlines(True),
                fromfile=name, tofile=name))
        return CandidateDiff(current.fingerprint, names, "".join(text), growth)

    def close(self):
        if getattr(self, "_promoted", None) is not None and not getattr(self, "_accepted", False):
            self.withdraw_unaccepted()
        if self._owned:
            self._owned.cleanup()

    def promote(self, *args, **kwargs):
        from sophyane.rsi_host_broker import promote_snapshot
        provider, evidence, allowed_paths = args
        require(provider, Operation.PROMOTION_OPERATION)
        self._promoted = promote_snapshot(
            self.repository,
            self.baseline,
            None,
            evidence,
            allowed_paths,
            candidate_source=self.path,
        )
        return self._promoted.candidate

    def withdraw_unaccepted(self):
        if self._promoted is None:
            return
        from sophyane.rsi_host_broker import rollback_snapshot
        rollback_snapshot(self._promoted)
        self._promoted = None

    def accept_promotion(self):
        self._accepted = True
