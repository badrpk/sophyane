from __future__ import annotations

import ctypes
import errno
import os
from pathlib import Path

import pytest

from sophyane.mutation import DEFAULT_LAB_ROOT, LabPathError, MutationLab
from sophyane.mutation import containment


def _source(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    root.mkdir()
    (root / "pkg").mkdir()
    (root / "pkg" / "module.py").write_text("VALUE = 1\n")
    return root


def test_default_lab_root_is_production_location() -> None:
    assert DEFAULT_LAB_ROOT == Path("/home/badrpk/shmry_mutation_lab")


def test_transaction_is_created_below_injected_lab_root(tmp_path: Path) -> None:
    source = _source(tmp_path)
    lab_root = tmp_path / "lab"

    transaction = MutationLab(lab_root).create_transaction(source)

    assert transaction.path.parent == lab_root
    assert transaction.path.is_dir()
    assert transaction.path != lab_root


def test_snapshot_is_immutable_and_source_is_unchanged(tmp_path: Path) -> None:
    source = _source(tmp_path)
    original = (source / "pkg" / "module.py").read_bytes()
    transaction = MutationLab(tmp_path / "lab").create_transaction(source)

    assert transaction.baseline_files["pkg/module.py"] == original
    transaction.apply_replacements({"pkg/module.py": "VALUE = 2\n"}, ("pkg/module.py",))

    assert (transaction.path / "pkg" / "module.py").read_text() == "VALUE = 2\n"
    assert (source / "pkg" / "module.py").read_bytes() == original
    assert transaction.baseline_files["pkg/module.py"] == original
    assert transaction.snapshot()["pkg/module.py"] == b"VALUE = 2\n"


def test_replacement_requires_allowlisted_relative_path(tmp_path: Path) -> None:
    transaction = MutationLab(tmp_path / "lab").create_transaction(_source(tmp_path))

    with pytest.raises(LabPathError, match="allowlist"):
        transaction.apply_replacements({"pkg/module.py": "x"}, ())


@pytest.mark.parametrize("bad_path", ["../outside", "pkg/../../outside"])
def test_rejects_traversal_paths(tmp_path: Path, bad_path: str) -> None:
    transaction = MutationLab(tmp_path / "lab").create_transaction(_source(tmp_path))

    with pytest.raises(LabPathError):
        transaction.apply_replacements({bad_path: "x"}, (bad_path,))


def test_rejects_absolute_paths(tmp_path: Path) -> None:
    transaction = MutationLab(tmp_path / "lab").create_transaction(_source(tmp_path))
    absolute = str(transaction.path / "pkg" / "module.py")

    with pytest.raises(LabPathError):
        transaction.apply_replacements({absolute: "x"}, (absolute,))


def test_rejects_source_symlinks(tmp_path: Path) -> None:
    source = _source(tmp_path)
    (source / "link.py").symlink_to(source / "pkg" / "module.py")

    with pytest.raises(LabPathError, match="symlink"):
        MutationLab(tmp_path / "lab").create_transaction(source)


@pytest.mark.parametrize("operation", ["copy", "snapshot"])
def test_filesystem_walk_errors_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    source = _source(tmp_path)
    transaction = MutationLab(tmp_path / "lab").create_transaction(source)
    original_walk = containment.os.walk

    def failing_walk(root, *args, **kwargs):
        if Path(root) in (source, transaction.path):
            error = PermissionError("directory became unreadable")
            onerror = kwargs.get("onerror")
            if onerror is None:
                return
            onerror(error)
        yield from original_walk(root, *args, **kwargs)

    monkeypatch.setattr(containment.os, "walk", failing_walk)
    if operation == "copy":
        with pytest.raises(PermissionError, match="unreadable"):
            MutationLab(tmp_path / "other-lab").create_transaction(source)
    else:
        with pytest.raises(PermissionError, match="unreadable"):
            transaction.snapshot()


def test_replacement_does_not_follow_target_symlink_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("keep me\n")
    transaction = MutationLab(tmp_path / "lab").create_transaction(source)
    target = transaction.path / "pkg" / "module.py"
    real_replace = containment.os.replace
    swapped = False

    def swap_before_replace(source_name, target_name, *args, **kwargs):
        nonlocal swapped
        if target_name == "module.py" and kwargs.get("dst_dir_fd") is not None and not swapped:
            target.unlink()
            target.symlink_to(outside)
            swapped = True
        return real_replace(source_name, target_name, *args, **kwargs)

    monkeypatch.setattr(containment.os, "replace", swap_before_replace)
    transaction.apply_replacements({"pkg/module.py": "MUTATED\n"}, ("pkg/module.py",))

    assert swapped
    assert outside.read_text() == "keep me\n"
    assert target.is_file() and not target.is_symlink()
    assert target.read_text() == "MUTATED\n"


def test_rejects_source_hard_links(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source(tmp_path)
    link = ctypes.CDLL(None, use_errno=True).link
    link.argtypes = (ctypes.c_char_p, ctypes.c_char_p)
    link.restype = ctypes.c_int
    result = link(
        os.fsencode(source / "pkg" / "module.py"),
        os.fsencode(source / "hardlink.py"),
    )
    if result != 0:
        error = ctypes.get_errno()
        if error in (errno.ENOSYS, errno.EOPNOTSUPP):
            pytest.skip(f"filesystem hard links unavailable: {os.strerror(error)}")
        if error not in (errno.EACCES, errno.EPERM):
            raise OSError(error, os.strerror(error))

        # Restricted Termux filesystems may deny link creation even when the
        # kernel supports it. Exercise the same st_nlink guard in that case.
        source_file = source / "pkg" / "module.py"
        original_lstat = Path.lstat

        def report_multiple_links(path: Path, *args, **kwargs):
            info = original_lstat(path, *args, **kwargs)
            if path == source_file:
                values = list(info)
                values[3] = 2
                return os.stat_result(values)
            return info

        monkeypatch.setattr(Path, "lstat", report_multiple_links)

    with pytest.raises(LabPathError, match="hard link"):
        MutationLab(tmp_path / "lab").create_transaction(source)


def test_restore_baseline_reverses_lab_candidate(tmp_path: Path) -> None:
    transaction = MutationLab(tmp_path / "lab").create_transaction(_source(tmp_path))
    transaction.apply_replacements({"pkg/module.py": "VALUE = 2\n"}, ("pkg/module.py",))

    patch = transaction.reversal_patch()
    transaction.restore_baseline()

    assert "VALUE = 2" in patch and "VALUE = 1" in patch
    assert transaction.snapshot()["pkg/module.py"] == b"VALUE = 1\n"


def test_restore_baseline_does_not_follow_target_symlink_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("keep me\n")
    transaction = MutationLab(tmp_path / "lab").create_transaction(source)
    transaction.apply_replacements({"pkg/module.py": "CANDIDATE\n"}, ("pkg/module.py",))
    target = transaction.path / "pkg" / "module.py"
    real_replace = containment.os.replace
    swapped = False

    def swap_before_replace(source_name, target_name, *args, **kwargs):
        nonlocal swapped
        if target_name == "module.py" and kwargs.get("dst_dir_fd") is not None and not swapped:
            target.unlink()
            target.symlink_to(outside)
            swapped = True
        return real_replace(source_name, target_name, *args, **kwargs)

    monkeypatch.setattr(containment.os, "replace", swap_before_replace)
    transaction.restore_baseline()

    assert swapped
    assert outside.read_text() == "keep me\n"
    assert target.is_file() and not target.is_symlink()
    assert target.read_text() == "VALUE = 1\n"


def test_restore_cleanup_walk_errors_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transaction = MutationLab(tmp_path / "lab").create_transaction(_source(tmp_path))
    transaction.apply_replacements({"pkg/module.py": "CANDIDATE\n"}, ("pkg/module.py",))
    original_walk = containment.os.walk

    def failing_cleanup_walk(root, *args, **kwargs):
        if Path(root) == transaction.path and kwargs.get("topdown") is False:
            error = PermissionError("cleanup directory became unreadable")
            onerror = kwargs.get("onerror")
            if onerror is None:
                return
            onerror(error)
        yield from original_walk(root, *args, **kwargs)

    monkeypatch.setattr(containment.os, "walk", failing_cleanup_walk)
    with pytest.raises(PermissionError, match="cleanup directory"):
        transaction.restore_baseline()
