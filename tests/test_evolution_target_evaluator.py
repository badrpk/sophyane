from pathlib import Path
import os
import subprocess

from sophyane.evolution.badrpk_targets import (
    resolve_target,
)
from sophyane.evolution.target_evaluator import (
    STATUS_PASS,
    STATUS_POLICY_REJECTED,
    STATUS_VALIDATION_UNAVAILABLE,
    evaluate_candidate_patch,
)


def git(
    repo: Path,
    *args: str,
) -> str:
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
        stderr=subprocess.PIPE,
    ).stdout


def init_repo(
    repo: Path,
    *,
    validator: bool,
    include_tests: bool = False,
) -> None:
    repo.mkdir(
        parents=True,
    )

    subprocess.run(
        (
            "git",
            "init",
            str(repo),
        ),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    git(
        repo,
        "config",
        "user.name",
        "V2C",
    )

    git(
        repo,
        "config",
        "user.email",
        "v2c@example.invalid",
    )

    (repo / "src").mkdir()

    (
        repo
        / "src"
        / "main.txt"
    ).write_text(
        "VALUE=1\n",
        encoding="utf-8",
    )

    if include_tests:
        (repo / "tests").mkdir()

        (
            repo
            / "tests"
            / "test.txt"
        ).write_text(
            "TEST=1\n",
            encoding="utf-8",
        )

    if validator:
        wrapper = repo / "gradlew"

        wrapper.write_text(
            "#!/usr/bin/env sh\n"
            "exit 0\n",
            encoding="utf-8",
        )

        wrapper.chmod(
            wrapper.stat().st_mode
            | 0o111
        )

    git(
        repo,
        "add",
        ".",
    )

    git(
        repo,
        "commit",
        "-m",
        "fixture",
    )


def make_patch(
    repo: Path,
    relative: str,
    content: str,
) -> str:
    path = repo / relative

    original = path.read_text(
        encoding="utf-8"
    )

    path.write_text(
        content,
        encoding="utf-8",
    )

    patch = git(
        repo,
        "diff",
        "--binary",
        "HEAD",
        "--",
        relative,
    )

    path.write_text(
        original,
        encoding="utf-8",
    )

    assert not git(
        repo,
        "status",
        "--porcelain",
    ).strip()

    return patch


def test_candidate_passes_in_disposable_worktree(
    tmp_path: Path,
):
    harness = tmp_path / "harness"
    target_repo = tmp_path / "target"

    init_repo(
        harness,
        validator=True,
    )

    init_repo(
        target_repo,
        validator=True,
    )

    target = resolve_target(
        name="Droidra",
        harness_repo=harness,
        explicit_repo=target_repo,
    )

    head = git(
        target_repo,
        "rev-parse",
        "HEAD",
    ).strip()

    patch = make_patch(
        target_repo,
        "src/main.txt",
        "VALUE=2\n",
    )

    result = evaluate_candidate_patch(
        target,
        patch,
    )

    assert result.status == STATUS_PASS
    assert result.passed

    assert (
        target_repo
        / "src"
        / "main.txt"
    ).read_text(
        encoding="utf-8"
    ) == "VALUE=1\n"

    assert git(
        target_repo,
        "rev-parse",
        "HEAD",
    ).strip() == head


def test_tests_are_validation_only(
    tmp_path: Path,
):
    harness = tmp_path / "harness"
    target_repo = tmp_path / "target"

    init_repo(
        harness,
        validator=True,
    )

    init_repo(
        target_repo,
        validator=True,
        include_tests=True,
    )

    target = resolve_target(
        name="Droidra",
        harness_repo=harness,
        explicit_repo=target_repo,
    )

    patch = make_patch(
        target_repo,
        "tests/test.txt",
        "TEST=2\n",
    )

    result = evaluate_candidate_patch(
        target,
        patch,
    )

    assert (
        result.status
        == STATUS_POLICY_REJECTED
    )


def test_no_validator_never_passes(
    tmp_path: Path,
):
    harness = tmp_path / "harness"
    target_repo = tmp_path / "target"

    init_repo(
        harness,
        validator=True,
    )

    init_repo(
        target_repo,
        validator=False,
    )

    target = resolve_target(
        name="rangoons",
        harness_repo=harness,
        explicit_repo=target_repo,
    )

    patch = make_patch(
        target_repo,
        "src/main.txt",
        "VALUE=2\n",
    )

    result = evaluate_candidate_patch(
        target,
        patch,
    )

    assert (
        result.status
        == STATUS_VALIDATION_UNAVAILABLE
    )

    assert not result.passed


def test_one_runnable_and_one_unavailable_validator_does_not_pass(
    tmp_path: Path,
):
    harness = tmp_path / "harness-mixed"
    target_repo = tmp_path / "target-mixed"

    init_repo(
        harness,
        validator=True,
    )

    init_repo(
        target_repo,
        validator=True,
        include_tests=True,
    )

    target = resolve_target(
        name="Droidra",
        harness_repo=harness,
        explicit_repo=target_repo,
    )

    patch = make_patch(
        target_repo,
        "src/main.txt",
        "VALUE=3\n",
    )

    result = evaluate_candidate_patch(
        target,
        patch,
    )

    # tests/ discovers pytest and gradlew discovers Gradle.
    # In environments without pytest, one runnable validator must
    # not hide another unavailable discovered validator.
    names = {
        check.spec.name: check
        for check in result.validator_checks
    }

    if (
        "python-pytest" in names
        and not names["python-pytest"].runnable
    ):
        assert (
            result.status
            == STATUS_VALIDATION_UNAVAILABLE
        )
        assert not result.passed
