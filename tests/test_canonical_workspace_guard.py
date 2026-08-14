from __future__ import annotations

from pathlib import Path

import sophyane.cli_entry as cli


def test_system32_launch_moves_to_sophyane_repo(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"

    repo = (
        home
        / "sophyane-repo"
    )

    repo.mkdir(
        parents=True,
    )

    (
        repo
        / "pyproject.toml"
    ).write_text(
        '[project]\n'
        'name="sophyane"\n',
        encoding="utf-8",
    )

    system32 = (
        tmp_path
        / "mnt/c/WINDOWS/system32"
    )

    system32.mkdir(
        parents=True,
    )

    # pathlib.Path.home() resolves through HOME on Linux.
    # The production helper imports Path locally, so patch the
    # environment rather than a nonexistent cli.Path symbol.
    monkeypatch.setenv(
        "HOME",
        str(home),
    )

    monkeypatch.chdir(
        system32
    )

    result = (
        cli._canonicalize_launch_workspace()
    )

    assert result == str(repo)
    assert Path.cwd() == repo


def test_normal_project_directory_is_preserved(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = (
        tmp_path
        / "real-project"
    )

    project.mkdir()

    monkeypatch.chdir(
        project
    )

    result = (
        cli._canonicalize_launch_workspace()
    )

    assert result is None
    assert Path.cwd() == project
