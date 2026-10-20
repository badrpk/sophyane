"""Durable, bounded inventory of configured Git checkouts."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from sophyane.rsi.repository_inventory import RepositoryInventory


def _git(path: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(path), *args], text=True
    ).strip()


def _repository(root: Path, folder: str, name: str) -> Path:
    path = root / folder
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "config", "user.name", "Inventory fixture")
    _git(path, "config", "user.email", "inventory@example.invalid")
    (path / "README.md").write_text(name, encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-qm", "initial")
    _git(path, "remote", "add", "origin", f"https://github.com/BADRPK/{name}.git")
    return path


def test_canonical_repository_id_and_metadata(tmp_path: Path) -> None:
    root = tmp_path / "repos"
    root.mkdir()
    repo = _repository(root, "checkout", "Widget")

    inventory = RepositoryInventory(tmp_path / "inventory.json", roots=[root], owner="badrpk")
    (record,) = inventory.refresh()

    assert record.repo_id == "badrpk/widget"
    assert record.path == str(repo.resolve())
    assert record.remote == "https://github.com/BADRPK/Widget.git"
    assert record.owner == "BADRPK"
    assert record.name == "Widget"
    assert record.commit == _git(repo, "rev-parse", "HEAD")
    assert record.branch == _git(repo, "branch", "--show-current")
    assert len(record.digest) == 64


def test_duplicate_checkouts_collapse_to_one_stable_record(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "repos"
    root.mkdir()
    first = _repository(root, "a", "widget")
    second = _repository(root, "b", "widget")

    inventory = RepositoryInventory(tmp_path / "inventory.json", roots=[root], owner="badrpk")

    assert [record.path for record in inventory.refresh()] == [str(first.resolve())]
    monkeypatch.chdir(second)
    assert [record.path for record in inventory.refresh()] == [str(first.resolve())]


def test_symlink_to_checkout_outside_root_is_ignored(tmp_path: Path) -> None:
    root = tmp_path / "repos"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    _repository(outside, "external", "external")
    (root / "external-link").symlink_to(outside / "external", target_is_directory=True)

    inventory = RepositoryInventory(tmp_path / "inventory.json", roots=[root], owner="badrpk")

    assert inventory.refresh() == ()


def test_cursor_advances_and_survives_restart(tmp_path: Path) -> None:
    root = tmp_path / "repos"
    root.mkdir()
    alpha = _repository(root, "alpha", "alpha")
    _repository(root, "beta", "beta")
    state = tmp_path / "inventory.json"
    inventory = RepositoryInventory(state, roots=[root], owner="badrpk")
    inventory.refresh()

    assert inventory.next_repository().repo_id == "badrpk/alpha"
    assert inventory.cursor.next_index == 1
    assert inventory.cursor.scanned_commits == {"badrpk/alpha": _git(alpha, "rev-parse", "HEAD")}

    restarted = RepositoryInventory(state, roots=[root], owner="badrpk")
    assert restarted.next_repository().repo_id == "badrpk/beta"
    assert restarted.next_repository().repo_id == "badrpk/alpha"
    assert restarted.cursor.next_index == 1
    assert json.loads(state.read_text(encoding="utf-8"))["cursor"]["next_index"] == 1


def test_missing_checkout_is_removed_from_persisted_inventory(tmp_path: Path) -> None:
    root = tmp_path / "repos"
    root.mkdir()
    repo = _repository(root, "alpha", "alpha")
    state = tmp_path / "inventory.json"
    inventory = RepositoryInventory(state, roots=[root], owner="badrpk")
    inventory.refresh()
    inventory.next_repository()
    repo.rename(tmp_path / "moved-outside-root")

    assert inventory.refresh() == ()
    assert inventory.next_repository() is None
    restarted = RepositoryInventory(state, roots=[root], owner="badrpk")
    assert restarted.records == ()
    assert restarted.cursor.scanned_commits == {}


def test_records_have_stable_canonical_order(tmp_path: Path) -> None:
    root = tmp_path / "repos"
    root.mkdir()
    _repository(root, "z-folder", "zeta")
    _repository(root, "a-folder", "alpha")
    inventory = RepositoryInventory(tmp_path / "inventory.json", roots=[root], owner="badrpk")

    assert [record.repo_id for record in inventory.refresh()] == ["badrpk/alpha", "badrpk/zeta"]
    assert [record.repo_id for record in inventory.refresh()] == ["badrpk/alpha", "badrpk/zeta"]


def test_cursor_keeps_next_repository_when_earlier_checkout_disappears(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repos"
    root.mkdir()
    alpha = _repository(root, "alpha", "alpha")
    _repository(root, "beta", "beta")
    _repository(root, "gamma", "gamma")
    state = tmp_path / "inventory.json"
    inventory = RepositoryInventory(state, roots=[root], owner="badrpk")

    assert inventory.next_repository().repo_id == "badrpk/alpha"
    alpha.rename(tmp_path / "moved-alpha")

    restarted = RepositoryInventory(state, roots=[root], owner="badrpk")
    assert restarted.next_repository().repo_id == "badrpk/beta"
    assert restarted.next_repository().repo_id == "badrpk/gamma"
