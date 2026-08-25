from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import subprocess

import sophyane.evolution.engine as engine_module
from sophyane.evolution.engine import EvolutionEngine


PATCH = """\
diff --git a/demo.py b/demo.py
--- a/demo.py
+++ b/demo.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
"""


def _git(
    repo: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
    )


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()

    _git(repo, "init", "-q")
    _git(
        repo,
        "config",
        "user.name",
        "promotion-test",
    )
    _git(
        repo,
        "config",
        "user.email",
        "promotion@test.invalid",
    )

    (repo / "demo.py").write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )

    _git(repo, "add", "demo.py")
    _git(repo, "commit", "-q", "-m", "base")

    head = _git(
        repo,
        "rev-parse",
        "HEAD",
    ).stdout.strip()

    return repo, head


def _engine(
    repo: Path,
    *,
    allow_promotion: bool = True,
) -> EvolutionEngine:
    engine = object.__new__(EvolutionEngine)

    engine.repo = repo

    engine.config = SimpleNamespace(
        full_test_command=(
            "python",
            "-c",
            "raise SystemExit(0)",
        ),
        allow_promotion=allow_promotion,
    )

    engine._generalization_tasks = (
        lambda capability: []
    )

    engine._score_generalization_tasks = (
        lambda *, repo, tasks: (
            1.0,
            {"promotion": True},
        )
    )

    return engine


def _record(run_id: str):
    return SimpleNamespace(
        proposal=SimpleNamespace(
            patch=PATCH,
            tests=(),
            component="runtime",
        ),
        run_id=run_id,
        task=SimpleNamespace(
            capability="promotion-test",
        ),
    )


def _worktree(
    repo: Path,
    run_id: str,
) -> Path:
    return (
        repo
        / ".sophyane-evolution"
        / "worktrees"
        / run_id
    )


def _branch_exists(
    repo: Path,
    run_id: str,
) -> bool:
    return (
        _git(
            repo,
            "show-ref",
            "--verify",
            "--quiet",
            "refs/heads/evolution/" + run_id,
            check=False,
        ).returncode
        == 0
    )


def _registered(
    repo: Path,
    worktree: Path,
) -> bool:
    return (
        str(worktree)
        in _git(
            repo,
            "worktree",
            "list",
            "--porcelain",
        ).stdout
    )


def test_promotion_git_add_failure_is_rejected_and_cleaned(
    tmp_path,
    monkeypatch,
):
    repo, base = _repo(tmp_path)

    run_id = "promotion-add-failure"

    engine = _engine(repo)

    real_run = engine_module.subprocess.run

    def fail_add(
        command,
        *args,
        **kwargs,
    ):
        cmd = list(command)

        if cmd == ["git", "add", "-A"]:
            raise subprocess.CalledProcessError(
                returncode=71,
                cmd=cmd,
                stderr="FAULT_PROMOTION_ADD_FAILURE",
            )

        return real_run(
            command,
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        engine_module.subprocess,
        "run",
        fail_add,
    )

    result = engine._gate(
        _record(run_id)
    )

    worktree = _worktree(
        repo,
        run_id,
    )

    assert result is not None
    assert result.promotable is False

    assert (
        result.details["promotion_stage"]
        == "git_add"
    )

    assert (
        result.details["promotion_returncode"]
        == 71
    )

    assert (
        result.details["promotion_committed"]
        is False
    )

    assert (
        "FAULT_PROMOTION_ADD_FAILURE"
        in result.details["promotion_error"]
    )

    assert not worktree.exists()
    assert not _registered(repo, worktree)
    assert not _branch_exists(repo, run_id)

    assert (
        _git(repo, "rev-parse", "HEAD")
        .stdout.strip()
        == base
    )


def test_promotion_git_commit_failure_is_rejected_and_cleaned(
    tmp_path,
    monkeypatch,
):
    repo, base = _repo(tmp_path)

    run_id = "promotion-commit-failure"

    engine = _engine(repo)

    real_run = engine_module.subprocess.run

    def fail_commit(
        command,
        *args,
        **kwargs,
    ):
        cmd = list(command)

        if (
            len(cmd) >= 2
            and cmd[0] == "git"
            and cmd[1] == "commit"
        ):
            raise subprocess.CalledProcessError(
                returncode=72,
                cmd=cmd,
                stderr=(
                    "FAULT_PROMOTION_COMMIT_FAILURE"
                ),
            )

        return real_run(
            command,
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        engine_module.subprocess,
        "run",
        fail_commit,
    )

    result = engine._gate(
        _record(run_id)
    )

    worktree = _worktree(
        repo,
        run_id,
    )

    assert result is not None
    assert result.promotable is False

    assert (
        result.details["promotion_stage"]
        == "git_commit"
    )

    assert (
        result.details["promotion_returncode"]
        == 72
    )

    assert (
        result.details["promotion_committed"]
        is False
    )

    assert (
        "FAULT_PROMOTION_COMMIT_FAILURE"
        in result.details["promotion_error"]
    )

    assert not worktree.exists()
    assert not _registered(repo, worktree)
    assert not _branch_exists(repo, run_id)

    assert (
        _git(repo, "rev-parse", "HEAD")
        .stdout.strip()
        == base
    )


def test_successful_promotion_remains_retained(
    tmp_path,
):
    repo, base = _repo(tmp_path)

    run_id = "successful-promotion"

    engine = _engine(repo)

    result = engine._gate(
        _record(run_id)
    )

    worktree = _worktree(
        repo,
        run_id,
    )

    try:
        assert result is not None
        assert result.promotable is True

        assert (
            result.details["promotion_committed"]
            is True
        )

        assert worktree.is_dir()
        assert _registered(repo, worktree)
        assert _branch_exists(repo, run_id)

        worktree_head = _git(
            worktree,
            "rev-parse",
            "HEAD",
        ).stdout.strip()

        assert worktree_head != base

        assert (
            _git(repo, "rev-parse", "HEAD")
            .stdout.strip()
            == base
        )

    finally:
        if (
            worktree.exists()
            or _registered(repo, worktree)
        ):
            _git(
                repo,
                "worktree",
                "remove",
                "--force",
                str(worktree),
            )

        _git(
            repo,
            "worktree",
            "prune",
        )

        if _branch_exists(
            repo,
            run_id,
        ):
            _git(
                repo,
                "branch",
                "-D",
                "evolution/" + run_id,
            )


def test_promotable_without_permission_is_retained_but_not_committed(
    tmp_path,
):
    repo, base = _repo(tmp_path)

    run_id = "promotable-no-permission"

    engine = _engine(
        repo,
        allow_promotion=False,
    )

    result = engine._gate(
        _record(run_id)
    )

    worktree = _worktree(
        repo,
        run_id,
    )

    try:
        assert result is not None
        assert result.promotable is True

        assert (
            result.details["promotion_committed"]
            is False
        )

        assert worktree.is_dir()
        assert _registered(repo, worktree)
        assert _branch_exists(repo, run_id)

        assert (
            _git(repo, "rev-parse", "HEAD")
            .stdout.strip()
            == base
        )

    finally:
        if (
            worktree.exists()
            or _registered(repo, worktree)
        ):
            _git(
                repo,
                "worktree",
                "remove",
                "--force",
                str(worktree),
            )

        _git(
            repo,
            "worktree",
            "prune",
        )

        if _branch_exists(
            repo,
            run_id,
        ):
            _git(
                repo,
                "branch",
                "-D",
                "evolution/" + run_id,
            )
