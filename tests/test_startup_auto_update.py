from __future__ import annotations

import subprocess
from pathlib import Path

import sophyane.startup_update as update


def _run(
    cwd: Path,
    *command: str,
    check: bool = True,
):
    return subprocess.run(
        list(command),
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def _git(
    repo: Path,
    *args: str,
    check: bool = True,
):
    return _run(
        repo,
        "git",
        *args,
        check=check,
    )


def _fixture(tmp_path: Path):
    remote = (
        tmp_path
        / "remote.git"
    )

    subprocess.run(
        [
            "git",
            "init",
            "--bare",
            "-q",
            str(remote),
        ],
        check=True,
    )

    seed = tmp_path / "seed"

    subprocess.run(
        [
            "git",
            "clone",
            "-q",
            str(remote),
            str(seed),
        ],
        check=True,
    )

    _git(
        seed,
        "config",
        "user.name",
        "updater-test",
    )

    _git(
        seed,
        "config",
        "user.email",
        "updater@test.invalid",
    )

    (seed / "value.txt").write_text(
        "one\n",
        encoding="utf-8",
    )

    _git(seed, "add", "value.txt")
    _git(seed, "commit", "-q", "-m", "one")
    _git(seed, "branch", "-M", "main")
    _git(seed, "push", "-q", "-u", "origin", "main")

    first = _git(
        seed,
        "rev-parse",
        "HEAD",
    ).stdout.strip()

    client = tmp_path / "client"

    subprocess.run(
        [
            "git",
            "clone",
            "-q",
            "-b",
            "main",
            str(remote),
            str(client),
        ],
        check=True,
    )

    return remote, seed, client, first


def _official_for_test(monkeypatch):
    monkeypatch.setattr(
        update,
        "_official_origin",
        lambda repo: True,
    )

    monkeypatch.setattr(
        update,
        "_sync_termux_dependencies",
        lambda repo, env: None,
    )

    monkeypatch.setattr(
        update,
        "_sync_python_dependencies",
        lambda repo: None,
    )

    monkeypatch.setattr(
        update,
        "_smoke_updated_install",
        lambda repo: None,
    )


def test_up_to_date_checkout_is_noop(
    tmp_path,
    monkeypatch,
):
    _, _, client, first = _fixture(
        tmp_path
    )

    _official_for_test(
        monkeypatch
    )

    result = (
        update.check_and_apply_startup_update(
            repo=client,
            env={},
            reexec=False,
        )
    )

    assert result.status == "up_to_date"
    assert result.local_head == first
    assert result.remote_head == first
    assert result.updated is False


def test_fast_forward_update_is_applied(
    tmp_path,
    monkeypatch,
):
    _, seed, client, first = _fixture(
        tmp_path
    )

    (seed / "value.txt").write_text(
        "two\n",
        encoding="utf-8",
    )

    _git(seed, "add", "value.txt")
    _git(seed, "commit", "-q", "-m", "two")
    _git(seed, "push", "-q", "origin", "main")

    second = _git(
        seed,
        "rev-parse",
        "HEAD",
    ).stdout.strip()

    assert second != first

    _official_for_test(
        monkeypatch
    )

    result = (
        update.check_and_apply_startup_update(
            repo=client,
            env={},
            reexec=False,
        )
    )

    assert result.status == "updated"
    assert result.updated is True
    assert result.local_head == first
    assert result.remote_head == second

    assert (
        _git(
            client,
            "rev-parse",
            "HEAD",
        ).stdout.strip()
        == second
    )

    assert (
        client
        / "value.txt"
    ).read_text(
        encoding="utf-8"
    ) == "two\n"


def test_dirty_checkout_is_preserved(
    tmp_path,
    monkeypatch,
):
    _, seed, client, first = _fixture(
        tmp_path
    )

    (seed / "value.txt").write_text(
        "two\n",
        encoding="utf-8",
    )

    _git(seed, "add", "value.txt")
    _git(seed, "commit", "-q", "-m", "two")
    _git(seed, "push", "-q", "origin", "main")

    (client / "local.txt").write_text(
        "developer change\n",
        encoding="utf-8",
    )

    _official_for_test(
        monkeypatch
    )

    result = (
        update.check_and_apply_startup_update(
            repo=client,
            env={},
            reexec=False,
        )
    )

    assert result.status == "dirty_worktree"

    assert (
        _git(
            client,
            "rev-parse",
            "HEAD",
        ).stdout.strip()
        == first
    )

    assert (
        client
        / "local.txt"
    ).read_text(
        encoding="utf-8"
    ) == "developer change\n"


def test_dependency_failure_rolls_source_back(
    tmp_path,
    monkeypatch,
):
    _, seed, client, first = _fixture(
        tmp_path
    )

    (seed / "value.txt").write_text(
        "two\n",
        encoding="utf-8",
    )

    _git(seed, "add", "value.txt")
    _git(seed, "commit", "-q", "-m", "two")
    _git(seed, "push", "-q", "origin", "main")

    _official_for_test(
        monkeypatch
    )

    calls = 0

    def fail_first_sync(repo):
        nonlocal calls
        calls += 1

        if calls == 1:
            raise RuntimeError(
                "FAULT_DEPENDENCY_INSTALL"
            )

    monkeypatch.setattr(
        update,
        "_sync_python_dependencies",
        fail_first_sync,
    )

    result = (
        update.check_and_apply_startup_update(
            repo=client,
            env={},
            reexec=False,
        )
    )

    assert result.status == "rolled_back"
    assert result.updated is False

    assert (
        _git(
            client,
            "rev-parse",
            "HEAD",
        ).stdout.strip()
        == first
    )

    assert (
        client
        / "value.txt"
    ).read_text(
        encoding="utf-8"
    ) == "one\n"


def test_keyboardinterrupt_is_not_swallowed(
    tmp_path,
    monkeypatch,
):
    _, seed, client, _ = _fixture(
        tmp_path
    )

    (seed / "value.txt").write_text(
        "two\n",
        encoding="utf-8",
    )

    _git(seed, "add", "value.txt")
    _git(seed, "commit", "-q", "-m", "two")
    _git(seed, "push", "-q", "origin", "main")

    _official_for_test(
        monkeypatch
    )

    monkeypatch.setattr(
        update,
        "_sync_python_dependencies",
        lambda repo: (
            (_ for _ in ()).throw(
                KeyboardInterrupt()
            )
        ),
    )

    try:
        update.check_and_apply_startup_update(
            repo=client,
            env={},
            reexec=False,
        )

    except KeyboardInterrupt:
        pass

    else:
        raise AssertionError(
            "KeyboardInterrupt must propagate"
        )



def test_termux_manifest_declares_postgresql():
    repo = Path(__file__).resolve().parents[1]

    manifest = (
        update._load_system_manifest(
            repo
        )
    )

    assert "postgresql" in manifest["termux"]
