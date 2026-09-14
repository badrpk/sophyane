"""Owned filesystem candidate snapshots, without Git or primary-tree resets."""
from dataclasses import dataclass
from pathlib import Path

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

import hashlib
import json
import difflib
import tempfile
from .authority import Operation, require

_EXCLUDED = {'.git', '.venv', '__pycache__', '.pytest_cache', 'node_modules'}

def snapshot(path, *, max_bytes=64 * 1024**2, max_files=10000):
    files, size = {}, 0
    import os
    for directory, dirs, names in os.walk(path, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in _EXCLUDED)
        for name in (*dirs, *sorted(names)):
            target = Path(directory) / name
            if target.is_symlink():
                raise PermissionError('Linked snapshot paths are forbidden')
        for name in sorted(names):
            target = Path(directory) / name
            if not target.is_file():
                raise PermissionError('Nonregular snapshot file')
            size += target.stat().st_size
            if size > max_bytes or len(files) >= max_files:
                raise ValueError('Snapshot budget exceeded')
            files[target.relative_to(path).as_posix()] = target.read_bytes()
    digest = hashlib.sha256()
    for name, value in sorted(files.items()):
        digest.update(name.encode() + b'\0' + hashlib.sha256(value).digest())
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
            raise PermissionError('Candidate root must be outside primary tree')
        self.baseline = snapshot(self.repository)
        self.root.mkdir(parents=True, exist_ok=True)
        self._owned = tempfile.TemporaryDirectory(prefix='rsi-', dir=self.root)
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
        """Host materialization of untrusted proposal data in an owned snapshot.

        This method never accepts authority assertions or touches primary source.
        Cloud authorization and independent re-verification are still mandatory.
        """
        self._replace_data(files, allowed_paths)

    def _replace_data(self, files, allowed_paths):
        if not self._owned or not self.path or self.path == self.repository:
            raise PermissionError('Owned isolated snapshot required')
        targets = []
        for name, content in files.items():
            relative = Path(name)
            if (name not in allowed_paths or relative.is_absolute() or '..' in relative.parts
                or any(part in _EXCLUDED for part in relative.parts) or not isinstance(content, str)):
                raise PermissionError('Unauthorized replacement path')
            target = self.path / relative
            if not target.resolve().is_relative_to(self.path):
                raise PermissionError('Replacement escapes candidate')
            for item in (target, *target.parents):
                if item == self.path:
                    break
                if item.is_symlink() or (item.is_file() and item.stat().st_nlink > 1):
                    raise PermissionError('Linked replacement')
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
            old, new = self.baseline.files.get(name, b''), current.files.get(name, b'')
            growth += len(new) - len(old)
            text.extend(difflib.unified_diff(old.decode('utf8', 'replace').splitlines(True),
                new.decode('utf8', 'replace').splitlines(True), fromfile=name, tofile=name))
        return CandidateDiff(current.fingerprint, names, ''.join(text), growth)

    def close(self):
        if self._promoted is not None and not self._accepted:
            self.withdraw_unaccepted()
        if self._owned:
            self._owned.cleanup()

    def promote(self, provider, evidence, allowed_paths):
        """Replace approved bytes only when the complete primary snapshot is unchanged.

        A process lock serializes promotions. Each file uses atomic replacement;
        failures restore only bytes written by this operation, never later edits.
        No Git command, index update or commit is performed.
        """
        require(provider, Operation.PROMOTION_OPERATION)
        import fcntl
        import os
        from .controller import protects_verification
        # Take an initial scope snapshot, then under the promotion lock take
        # exactly one fresh candidate snapshot that supplies both the verified
        # fingerprint check and every byte written to the primary repository.
        initial = snapshot(self.path)
        changed_files = tuple(sorted(
            name for name in set(initial.files) | set(self.baseline.files)
            if initial.files.get(name) != self.baseline.files.get(name)
        ))
        if (not evidence.accepted or
            not set(changed_files) <= allowed_paths or
            not protects_verification(changed_files, ())):
            raise PermissionError('Promotion lacks exact verified scope')

        with (self.root / 'promotion.lock').open('a+') as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            if snapshot(self.repository).fingerprint != self.baseline.fingerprint:
                raise PermissionError('Primary tree changed since baseline')

            current = snapshot(self.path)

            if current.fingerprint != evidence.fingerprint:
                raise PermissionError('Candidate changed after verification')

            changed_files = tuple(sorted(
                name for name in set(current.files) | set(self.baseline.files)
                if current.files.get(name) != self.baseline.files.get(name)
            ))

            if (not set(changed_files) <= allowed_paths or
                not protects_verification(changed_files, ())):
                raise PermissionError('Promotion lacks exact verified scope')

            if any(name not in current.files for name in changed_files):
                raise PermissionError('Deletion promotion is forbidden')
            written = []
            try:
                for name in changed_files:
                    target = self.repository / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    # Recheck each target just before replacing it.
                    old = self.baseline.files.get(name)
                    if (target.read_bytes() if target.exists() else None) != old:
                        raise PermissionError('Concurrent foreground edit')
                    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
                        temporary = Path(stream.name)
                        stream.write(current.files[name])
                        stream.flush()
                        os.fsync(stream.fileno())
                    try:
                        if target.exists():
                            temporary.chmod(target.stat().st_mode & 0o777)
                        temporary.replace(target)
                    finally:
                        temporary.unlink(missing_ok=True)
                    written.append(name)
            except BaseException:
                for name in reversed(written):
                    target = self.repository / name
                    if target.read_bytes() == current.files[name]:
                        if name in self.baseline.files:
                            target.write_bytes(self.baseline.files[name])
                        else:
                            target.unlink()
                raise
            self._promoted = {name: current.files[name] for name in changed_files}
            return current.fingerprint

    def withdraw_unaccepted(self):
        """Withdraw only our still-identical bytes, preserving concurrent user edits."""
        if self._promoted is None:
            return
        for name, promoted in self._promoted.items():
            target = self.repository / name
            if target.is_file() and not target.is_symlink() and target.read_bytes() == promoted:
                original = self.baseline.files.get(name)
                if original is None:
                    target.unlink()
                else:
                    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
                        temporary = Path(stream.name)
                        stream.write(original)
                    temporary.chmod(target.stat().st_mode & 0o777)
                    temporary.replace(target)
        self._promoted = None

    def accept_promotion(self):
        self._accepted = True
