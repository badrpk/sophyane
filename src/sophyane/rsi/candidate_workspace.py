"""Owned filesystem candidate snapshots; never a primary-tree transaction."""
from dataclasses import dataclass
from pathlib import Path
import difflib
import hashlib
import os
import tempfile

from .authority import Operation, require

_EXCLUDED = {
    ".git", ".venv", "__pycache__", ".pytest_cache", "node_modules",
    # Large unrelated Android build checkout; it is outside the configured RSI
    # experiment scope and would otherwise consume the whole snapshot budget.
    "termux-x11",
    # Generated guest/build artifacts are not source candidates and can be
    # hundreds of megabytes on the development device.
    ".alpine-initrd-root", ".alpine-minimal-root", ".alpine-modloop-extract",
    ".alpine-qemu-test", ".qemu-initrd-root", ".qemu-initrd-original",
    ".sophyane-smoke", ".sophyane-state",
    ".sophyane-rsi-state", ".local",
    # Durable RSI control state is outside candidate source scope and changes
    # while a bounded experiment is running. Including it would make the
    # primary snapshot appear mutated during an otherwise isolated run.
    "curriculum.json", "curriculum.events.jsonl", "heartbeat.json", "stages.jsonl",
    "weaknesses.json", "metrics.json", "repository-inventory.json", "safety-halt.json",
    "rsi.pid", "rsi-child.pid", "rsi.log",
    # Runtime control sockets are not repository inputs and are not regular
    # files; including them makes an otherwise valid snapshot fail closed.
    "rsi.sock",
}
_IMMUTABLE_RSI_TRUST_ROOTS = frozenset({
    "src/sophyane/intelligence_authority.py",
    "src/sophyane/rsi_host_broker.py",
})
_RUNTIME_PID_FILES = ("rsi.pid", "rsi-child.pid")
_RUNTIME_LOCK_FILES = ("rsi.pid.lock", "cloud-availability.lock")
_RSI_COMMAND_MARKERS = ("sophyane.rsi_terminal", "sophyane.rsi.supervisor")


def _default_process_is_alive(pid):
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _default_command_line_reader(pid):
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(
            "utf-8", "replace"
        )
    except OSError:
        return None


def _remove_unlocked(path):
    try:
        import fcntl
        handle = path.open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        try:
            path.unlink(missing_ok=True)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
        return True
    except (OSError, ImportError):
        return False


def reconcile_stale_runtime_artifacts(
    candidate_root,
    *,
    process_is_alive=None,
    command_line_reader=None,
):
    """Remove stale RSI PID/lock markers without deleting candidate evidence."""
    root = Path(candidate_root)
    process_is_alive = process_is_alive or _default_process_is_alive
    command_line_reader = command_line_reader or _default_command_line_reader
    if not root.is_dir():
        return
    workspaces = [root] + sorted((item for item in root.iterdir() if item.is_dir()), key=str)
    for workspace in workspaces:
        for name in _RUNTIME_PID_FILES:
            path = workspace / name
            if not path.is_file():
                continue
            try:
                pid = int(path.read_text(encoding="utf-8").strip())
            except (OSError, TypeError, ValueError):
                pid = 0
            stale = not process_is_alive(pid)
            if not stale:
                command_line = command_line_reader(pid)
                stale = command_line is not None and not any(
                    marker in command_line for marker in _RSI_COMMAND_MARKERS
                )
            if stale:
                path.unlink(missing_ok=True)
        if not any((workspace / name).exists() for name in _RUNTIME_PID_FILES):
            for name in _RUNTIME_LOCK_FILES:
                path = workspace / name
                if path.is_file():
                    _remove_unlocked(path)


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
        # Symlinked baseline artifacts are outside the candidate snapshot. They
        # must not block an otherwise isolated run, and they are never eligible
        # for promotion because replacement validation still rejects links.
        dirs[:] = sorted(
            d for d in dirs
            if d not in _EXCLUDED and not (Path(directory) / d).is_symlink()
        )
        regular_names = [
            name for name in sorted(names)
            if name not in _EXCLUDED and not (Path(directory) / name).is_symlink()
        ]
        for name in regular_names:
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
