from pathlib import Path
import subprocess

import pytest

from sophyane.evolution.badrpk_targets import (
    resolve_target,
)
from sophyane.evolution.engine import EvolutionEngine
from sophyane.evolution.models import EvolutionConfig
from sophyane.evolution.target_policy import (
    build_target_policy,
)
from sophyane.evolution.target_worktree import (
    create_target_worktree,
    remove_target_worktree,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        (
            "git",
            "-C",
            str(repo),
            *args,
        ),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()


def _init_repo(path: Path) -> None:
    path.mkdir(
        parents=True,
        exist_ok=True,
    )

    subprocess.run(
        (
            "git",
            "init",
            str(path),
        ),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    _git(
        path,
        "config",
        "user.email",
        "v2b@example.invalid",
    )

    _git(
        path,
        "config",
        "user.name",
        "Sophyane V2B",
    )

    (path / "src").mkdir()
    (path / "src" / "main.py").write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )

    (path / "pyproject.toml").write_text(
        "[project]\n"
        'name = "fixture"\n'
        'version = "0.0.0"\n',
        encoding="utf-8",
    )

    _git(
        path,
        "add",
        ".",
    )

    _git(
        path,
        "commit",
        "-m",
        "fixture",
    )


def test_policy_discovers_source_and_validator(
    tmp_path: Path,
):
    harness = tmp_path / "harness"
    target_repo = tmp_path / "target"

    _init_repo(harness)
    _init_repo(target_repo)

    target = resolve_target(
        name="rangoons",
        harness_repo=harness,
        explicit_repo=target_repo,
    )

    policy = build_target_policy(target)

    assert Path("src") in policy.source_roots

    assert any(
        item.name == "python-pytest"
        for item in policy.validators
    )

    assert policy.path_is_candidate_source(
        target_repo / "src" / "main.py"
    )

    assert not policy.path_is_candidate_source(
        target_repo / ".git" / "config"
    )


def test_target_worktree_is_detached_and_isolated(
    tmp_path: Path,
):
    harness = tmp_path / "harness"
    target_repo = tmp_path / "target"

    _init_repo(harness)
    _init_repo(target_repo)

    target = resolve_target(
        name="xerus",
        harness_repo=harness,
        explicit_repo=target_repo,
    )

    original_head = _git(
        target_repo,
        "rev-parse",
        "HEAD",
    )

    worktree = create_target_worktree(
        target,
        root=tmp_path / "worktrees",
    )

    try:
        assert worktree.exists
        assert worktree.source_head == original_head

        assert _git(
            worktree.path,
            "rev-parse",
            "HEAD",
        ) == original_head

        branch = _git(
            worktree.path,
            "branch",
            "--show-current",
        )

        assert branch == ""

        (worktree.path / "src" / "main.py").write_text(
            "VALUE = 2\n",
            encoding="utf-8",
        )

        assert (
            target_repo
            / "src"
            / "main.py"
        ).read_text(
            encoding="utf-8"
        ) == "VALUE = 1\n"

        # Restore the disposable worktree so normal cleanup is
        # intentionally non-destructive.
        _git(
            worktree.path,
            "restore",
            "src/main.py",
        )

    finally:
        remove_target_worktree(worktree)

    assert not worktree.path.exists()

    assert _git(
        target_repo,
        "rev-parse",
        "HEAD",
    ) == original_head


def test_engine_still_executes_from_harness(
    tmp_path: Path,
):
    harness = tmp_path / "harness"
    target_repo = tmp_path / "target"

    _init_repo(harness)
    _init_repo(target_repo)

    engine = EvolutionEngine(
        EvolutionConfig(
            repo=harness,
            target_name="shmry",
            target_repo=target_repo,
        )
    )

    assert engine.repo == harness.resolve()
    assert engine.harness_repo == harness.resolve()
    assert engine.target_repo == target_repo.resolve()
    assert engine.target_policy.repo == target_repo.resolve()
