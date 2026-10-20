"""Copy-on-write transaction storage confined to a mutation lab."""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import stat
import tempfile
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Iterable, Mapping

DEFAULT_LAB_ROOT = Path("/home/badrpk/shmry_mutation_lab")


class LabPathError(ValueError):
    """A source tree or requested path violates lab containment rules."""


def _relative_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise LabPathError(f"invalid relative path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")):
        raise LabPathError(f"path must be relative and cannot traverse: {value!r}")
    return path


def _hash_files(files: Mapping[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name, content in sorted(files.items()):
        encoded = name.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


class MutationLab:
    """Creates isolated transaction copies beneath a configured lab root."""

    def __init__(self, lab_root: Path = DEFAULT_LAB_ROOT):
        self.lab_root = Path(lab_root).expanduser().absolute()

    def create_transaction(self, source_root: Path) -> "LabTransaction":
        requested_source = Path(source_root).expanduser().absolute()
        if stat.S_ISLNK(requested_source.lstat().st_mode):
            raise LabPathError(f"source root is a symlink: {requested_source}")
        source = requested_source.resolve(strict=True)
        if not source.is_dir():
            raise LabPathError(f"source root is not a directory: {source}")
        lab = self.lab_root.resolve(strict=False)
        if source == lab or source in lab.parents or lab in source.parents:
            raise LabPathError("source root and mutation lab must not contain one another")
        lab.mkdir(parents=True, exist_ok=True)
        lab = lab.resolve(strict=True)
        if source == lab or source in lab.parents or lab in source.parents:
            raise LabPathError("source root and mutation lab must not contain one another")
        if not lab.is_dir():
            raise LabPathError("mutation lab root is not a directory")

        transaction_path = Path(tempfile.mkdtemp(prefix="mutation-", dir=lab))
        transaction = LabTransaction(transaction_path, source)
        try:
            transaction._copy_source()
        except BaseException:
            transaction.close()
            shutil.rmtree(transaction_path)
            raise
        return transaction


class LabTransaction:
    """An isolated regular-file snapshot and reversible candidate workspace."""

    def __init__(self, path: Path, source_root: Path):
        self.path = path.resolve(strict=True)
        self.source_root = source_root
        self.transaction_id = self.path.name.removeprefix("mutation-")
        self._baseline: dict[str, bytes] = {}
        self._closed = False
        self._root_fd = os.open(
            self.path,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )

    @staticmethod
    def _raise_walk_error(error: OSError) -> None:
        raise error

    @property
    def baseline_files(self) -> Mapping[str, bytes]:
        return MappingProxyType(self._baseline.copy())

    @property
    def baseline_hash(self) -> str:
        return _hash_files(self._baseline)

    def _copy_source(self) -> None:
        for current, directories, filenames in os.walk(
            self.source_root, followlinks=False, onerror=self._raise_walk_error
        ):
            current_path = Path(current)
            kept_dirs: list[str] = []
            for directory in directories:
                item = current_path / directory
                info = item.lstat()
                if stat.S_ISLNK(info.st_mode):
                    raise LabPathError(f"source contains symlink: {item}")
                if not stat.S_ISDIR(info.st_mode):
                    raise LabPathError(f"source contains non-directory entry: {item}")
                kept_dirs.append(directory)
                (self.path / item.relative_to(self.source_root)).mkdir(exist_ok=True)
            directories[:] = kept_dirs
            for filename in filenames:
                item = current_path / filename
                info = item.lstat()
                if stat.S_ISLNK(info.st_mode):
                    raise LabPathError(f"source contains symlink: {item}")
                if not stat.S_ISREG(info.st_mode):
                    raise LabPathError(f"source contains non-regular file: {item}")
                if info.st_nlink != 1:
                    raise LabPathError(f"source contains hard link: {item}")
                relative = item.relative_to(self.source_root).as_posix()
                flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(item, flags)
                try:
                    opened = os.fstat(descriptor)
                    if (opened.st_dev, opened.st_ino, opened.st_nlink) != (info.st_dev, info.st_ino, 1):
                        raise LabPathError(f"source changed during snapshot: {item}")
                    with os.fdopen(descriptor, "rb", closefd=False) as source_file:
                        content = source_file.read()
                finally:
                    os.close(descriptor)
                target = self.path / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                self._baseline[relative] = content

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("mutation transaction is closed")

    def _open_parent_directory(self, parts: tuple[str, ...]) -> int:
        descriptor = os.dup(self._root_fd)
        try:
            for part in parts:
                next_descriptor = os.open(
                    part,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=descriptor,
                )
                os.close(descriptor)
                descriptor = next_descriptor
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def _atomic_replace_text(self, name: str, text: str) -> None:
        parts = _relative_path(name).parts
        parent_fd = self._open_parent_directory(parts[:-1])
        temp_name = f".mutation-{secrets.token_hex(12)}.tmp"
        temp_fd = -1
        try:
            target_info = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
            if not stat.S_ISREG(target_info.st_mode):
                raise LabPathError(f"replacement target is not a regular file: {name!r}")
            temp_fd = os.open(
                temp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                stat.S_IMODE(target_info.st_mode),
                dir_fd=parent_fd,
            )
            data = text.encode("utf-8")
            offset = 0
            while offset < len(data):
                offset += os.write(temp_fd, data[offset:])
            os.close(temp_fd)
            temp_fd = -1
            os.replace(
                temp_name,
                parts[-1],
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
        finally:
            if temp_fd >= 0:
                os.close(temp_fd)
            try:
                os.unlink(temp_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            os.close(parent_fd)

    def _checked_target(self, relative: str) -> Path:
        parsed = _relative_path(relative)
        target = self.path.joinpath(*parsed.parts)
        if not target.resolve(strict=False).is_relative_to(self.path):
            raise LabPathError(f"path escapes transaction: {relative!r}")
        cursor = self.path
        for part in parsed.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise LabPathError(f"transaction path contains symlink: {relative!r}")
        return target

    def apply_replacements(self, replacements: Mapping[str, str], allowed_paths: Iterable[str]) -> None:
        self._ensure_open()
        allowed = {_relative_path(path).as_posix() for path in allowed_paths}
        checked: list[tuple[Path, str]] = []
        for name, text in replacements.items():
            normalized = _relative_path(name).as_posix()
            if normalized not in allowed:
                raise LabPathError(f"path is not in the allowlist: {name!r}")
            if not isinstance(text, str):
                raise LabPathError("replacement values must be text")
            target = self._checked_target(normalized)
            if normalized not in self._baseline or not target.is_file():
                raise LabPathError(f"replacement target is not a snapshotted regular file: {name!r}")
            info = target.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise LabPathError(f"replacement target is not a single-link regular file: {name!r}")
            checked.append((target, text))
        for target, text in checked:
            self._atomic_replace_text(target.relative_to(self.path).as_posix(), text)

    def snapshot(self) -> Mapping[str, bytes]:
        self._ensure_open()
        files: dict[str, bytes] = {}
        for current, directories, filenames in os.walk(
            self.path, followlinks=False, onerror=self._raise_walk_error
        ):
            current_path = Path(current)
            for directory in directories:
                if (current_path / directory).is_symlink():
                    raise LabPathError("transaction contains symlink")
            for filename in filenames:
                item = current_path / filename
                info = item.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise LabPathError("transaction contains non-regular or hard-linked file")
                files[item.relative_to(self.path).as_posix()] = item.read_bytes()
        return MappingProxyType(files)

    def reversal_patch(self) -> str:
        import difflib

        candidate = self.snapshot()
        chunks: list[str] = []
        for name in sorted(set(candidate) | set(self._baseline)):
            before = self._baseline.get(name, b"").decode("utf-8", errors="replace").splitlines(keepends=True)
            after = candidate.get(name, b"").decode("utf-8", errors="replace").splitlines(keepends=True)
            chunks.extend(difflib.unified_diff(after, before, fromfile=f"candidate/{name}", tofile=f"baseline/{name}"))
        return "".join(chunks)

    def restore_baseline(self) -> None:
        self._ensure_open()
        for name in sorted(set(self.snapshot()) | set(self._baseline)):
            target = self._checked_target(name)
            if name in self._baseline:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(self._baseline[name])
            elif target.exists():
                target.unlink()
        for current, directories, _ in os.walk(self.path, topdown=False):
            current_path = Path(current)
            for directory in directories:
                child = current_path / directory
                if child.is_dir() and not any(child.iterdir()):
                    child.rmdir()

    def close(self) -> None:
        if not self._closed:
            os.close(self._root_fd)
            self._closed = True
