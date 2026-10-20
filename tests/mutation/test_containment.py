from __future__ import annotations

import ctypes
import errno
import os
from pathlib import Path

import pytest

from sophyane.mutation import DEFAULT_LAB_ROOT, LabPathError, MutationLab


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


def test_rejects_source_hard_links(tmp_path: Path) -> None:
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
        if error in (errno.EACCES, errno.ENOSYS, errno.EPERM, errno.EOPNOTSUPP):
            pytest.skip(f"filesystem hard links unavailable: {os.strerror(error)}")
        raise OSError(error, os.strerror(error))

    with pytest.raises(LabPathError, match="hard link"):
        MutationLab(tmp_path / "lab").create_transaction(source)


def test_restore_baseline_reverses_lab_candidate(tmp_path: Path) -> None:
    transaction = MutationLab(tmp_path / "lab").create_transaction(_source(tmp_path))
    transaction.apply_replacements({"pkg/module.py": "VALUE = 2\n"}, ("pkg/module.py",))

    patch = transaction.reversal_patch()
    transaction.restore_baseline()

    assert "VALUE = 2" in patch and "VALUE = 1" in patch
    assert transaction.snapshot()["pkg/module.py"] == b"VALUE = 1\n"
