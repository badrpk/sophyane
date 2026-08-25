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


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()

    _git(repo, "init", "-q")
    _git(
        repo,
        "config",
        "user.name",
        "evolution-test",
    )
    _git(
        repo,
        "config",
        "user.email",
        "evolution@test.invalid",
    )

    (repo / "demo.py").write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )

    _git(repo, "add", "demo.py")
    _git(repo, "commit", "-q", "-m", "base")

    return repo


def _engine(
    repo: Path,
    *,
    regression_command: tuple[str, ...],
) -> EvolutionEngine:
    engine = object.__new__(EvolutionEngine)

    engine.repo = repo

    engine.config = SimpleNamespace(
        full_test_command=regression_command,
        allow_promotion=False,
    )

    engine._generalization_tasks = (
        lambda capability: []
    )

    engine._score_generalization_tasks = (
        lambda *, repo, tasks: (
            1.0,
            {"test": True},
        )
    )

    return engine


def _record(
    *,
    run_id: str,
    tests: tuple[str, ...],
):
    return SimpleNamespace(
        proposal=SimpleNamespace(
            patch=PATCH,
            tests=tests,
            component="runtime",
        ),
        run_id=run_id,
        task=SimpleNamespace(
            capability="fault-injection",
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


def _worktree_registered(
    repo: Path,
    worktree: Path,
) -> bool:
    result = _git(
        repo,
        "worktree",
        "list",
        "--porcelain",
    )

    return str(worktree) in result.stdout


def test_targeted_timeout_is_rejected_and_cleaned(
    tmp_path,
    monkeypatch,
):
    repo = _repo(tmp_path)

    run_id = "targeted-timeout"

    engine = _engine(
        repo,
        regression_command=(
            "python",
            "-c",
            "raise SystemExit(0)",
        ),
    )

    record = _record(
        run_id=run_id,
        tests=("tests/test_fault.py",),
    )

    worktree = _worktree(
        repo,
        run_id,
    )

    real_run = engine_module.subprocess.run

    def injected_run(
        command,
        *args,
        **kwargs,
    ):
        cmd = list(command)

        if (
            len(cmd) >= 3
            and cmd[0] == "python"
            and cmd[1] == "-m"
            and cmd[2] == "pytest"
        ):
            raise subprocess.TimeoutExpired(
                cmd=cmd,
                timeout=300,
                output="TARGETED_OUT",
                stderr="TARGETED_ERR",
            )

        return real_run(
            command,
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        engine_module.subprocess,
        "run",
        injected_run,
    )

    result = engine._gate(record)

    assert result is not None
    assert result.targeted_passed is False
    assert result.regression_passed is False
    assert result.promotable is False

    assert (
        result.details["timeout_stage"]
        == "targeted"
    )

    assert result.details["timeout_seconds"] == 300

    assert not worktree.exists()
    assert not _worktree_registered(repo, worktree)
    assert not _branch_exists(repo, run_id)


def test_regression_timeout_is_rejected_and_cleaned(
    tmp_path,
    monkeypatch,
):
    repo = _repo(tmp_path)

    run_id = "regression-timeout"

    regression_command = (
        "python",
        "-c",
        "print('REGRESSION_SENTINEL')",
    )

    engine = _engine(
        repo,
        regression_command=regression_command,
    )

    record = _record(
        run_id=run_id,
        tests=(),
    )

    worktree = _worktree(
        repo,
        run_id,
    )

    real_run = engine_module.subprocess.run

    def injected_run(
        command,
        *args,
        **kwargs,
    ):
        cmd = list(command)

        if cmd == list(regression_command):
            raise subprocess.TimeoutExpired(
                cmd=cmd,
                timeout=900,
                output="REGRESSION_OUT",
                stderr="REGRESSION_ERR",
            )

        return real_run(
            command,
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        engine_module.subprocess,
        "run",
        injected_run,
    )

    result = engine._gate(record)

    assert result is not None

    assert result.targeted_passed is True
    assert result.regression_passed is False
    assert result.promotable is False

    assert (
        result.details["timeout_stage"]
        == "regression"
    )

    assert result.details["timeout_seconds"] == 900

    assert not worktree.exists()
    assert not _worktree_registered(repo, worktree)
    assert not _branch_exists(repo, run_id)


def test_apply_rejection_is_cleaned(
    tmp_path,
):
    repo = _repo(tmp_path)

    run_id = "apply-rejected"

    engine = _engine(
        repo,
        regression_command=(
            "python",
            "-c",
            "raise SystemExit(0)",
        ),
    )

    bad_record = SimpleNamespace(
        proposal=SimpleNamespace(
            patch="""\
diff --git a/missing.py b/missing.py
--- a/missing.py
+++ b/missing.py
@@ -1 +1 @@
-OLD
+NEW
""",
            tests=(),
            component="runtime",
        ),
        run_id=run_id,
        task=SimpleNamespace(
            capability="fault-injection",
        ),
    )

    worktree = _worktree(
        repo,
        run_id,
    )

    result = engine._gate(
        bad_record
    )

    assert result is not None
    assert result.promotable is False
    assert "apply_error" in result.details

    assert not worktree.exists()
    assert not _worktree_registered(repo, worktree)
    assert not _branch_exists(repo, run_id)


def test_promotable_candidate_is_retained_for_inspection(
    tmp_path,
):
    repo = _repo(tmp_path)

    run_id = "promotable-candidate"

    engine = _engine(
        repo,
        regression_command=(
            "python",
            "-c",
            "raise SystemExit(0)",
        ),
    )

    record = _record(
        run_id=run_id,
        tests=(),
    )

    worktree = _worktree(
        repo,
        run_id,
    )

    result = engine._gate(
        record
    )

    try:
        assert result is not None
        assert result.targeted_passed is True
        assert result.regression_passed is True
        assert result.held_out_passed is True
        assert result.promotable is True

        assert worktree.is_dir()
        assert _worktree_registered(
            repo,
            worktree,
        )
        assert _branch_exists(
            repo,
            run_id,
        )

    finally:
        if (
            worktree.exists()
            or _worktree_registered(
                repo,
                worktree,
            )
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
