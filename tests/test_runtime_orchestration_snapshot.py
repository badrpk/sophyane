from __future__ import annotations

import hashlib
from pathlib import Path

from sophyane.runtime_orchestration_patch import _snapshot


def test_snapshot_preserves_workspace_artifact_contract(
    tmp_path: Path,
):
    artifact = tmp_path / "proof.txt"
    artifact.write_bytes(b"proof")

    snapshot = _snapshot(tmp_path)

    assert snapshot == {
        "proof.txt": hashlib.sha256(b"proof").hexdigest(),
    }


def test_snapshot_excludes_runtime_and_repository_noise(
    tmp_path: Path,
):
    keep = tmp_path / "src" / "app.py"
    keep.parent.mkdir()
    keep.write_text("print('ok')", encoding="utf-8")

    excluded = [
        tmp_path / ".git" / "objects" / "aa",
        tmp_path / ".venv" / "lib" / "package.py",
        tmp_path / "__pycache__" / "app.cpython-313.pyc",
        tmp_path / ".pytest_cache" / "state",
        tmp_path / "node_modules" / "pkg" / "index.js",
    ]

    for path in excluded:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"noise")

    snapshot = _snapshot(tmp_path)

    assert "src/app.py" in snapshot

    for path in snapshot:
        parts = Path(path).parts

        assert ".git" not in parts
        assert ".venv" not in parts
        assert "__pycache__" not in parts
        assert ".pytest_cache" not in parts
        assert "node_modules" not in parts
        assert not path.endswith(".pyc")


def test_snapshot_still_detects_new_exact_write(
    tmp_path: Path,
):
    before = _snapshot(tmp_path)

    path = tmp_path / "event.txt"
    path.write_bytes(b"exact bytes")

    after = _snapshot(tmp_path)

    assert "event.txt" not in before
    assert after["event.txt"] == hashlib.sha256(
        b"exact bytes"
    ).hexdigest()


def test_snapshot_serializes_nested_paths_with_forward_slashes(
    tmp_path: Path,
):
    nested = (
        tmp_path
        / "src"
        / "package"
        / "module.py"
    )
    nested.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    nested.write_bytes(b"portable")

    snapshot = _snapshot(tmp_path)

    expected = "src/package/module.py"

    assert expected in snapshot
    assert snapshot[expected] == hashlib.sha256(
        b"portable"
    ).hexdigest()

    # Snapshot keys are a serialized cross-platform contract,
    # not native filesystem display paths.
    assert all("\\" not in key for key in snapshot)
