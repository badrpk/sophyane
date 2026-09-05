from pathlib import Path
import os
import subprocess

import pytest

from sophyane.evolution.badrpk_targets import (
    resolve_target,
)
from sophyane.evolution.target_evaluator import (
    STATUS_PASS,
    STATUS_PATCH_INVALID,
    STATUS_POLICY_REJECTED,
    STATUS_VALIDATION_FAILED,
    STATUS_VALIDATION_UNAVAILABLE,
    evaluate_candidate_patch,
    evaluate_candidate_patch_from_snapshot,
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

def snapshot_patch(
    old: str,
    new: str,
    *,
    relative: str = "src/main.txt",
) -> str:
    return (
        f"diff --git a/{relative} b/{relative}\n"
        f"--- a/{relative}\n"
        f"+++ b/{relative}\n"
        "@@ -1 +1 @@\n"
        f"-{old}\n"
        f"+{new}\n"
    )


def test_snapshot_candidate_passes_without_mutating_dirty_target(
    tmp_path: Path,
):
    harness = tmp_path / "snapshot-harness"
    target_repo = tmp_path / "snapshot-target"

    init_repo(harness, validator=True)
    init_repo(target_repo, validator=True)

    wrapper = target_repo / "gradlew"
    wrapper.write_text(
        "#!/usr/bin/env sh\n"
        "grep -q '^VALUE=3$' src/main.txt\n",
        encoding="utf-8",
    )
    wrapper.chmod(wrapper.stat().st_mode | 0o111)
    git(target_repo, "add", "gradlew")
    git(target_repo, "commit", "--amend", "--no-edit")

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

    main = target_repo / "src" / "main.txt"
    main.write_text("VALUE=2\n", encoding="utf-8")
    status_before = git(
        target_repo,
        "status",
        "--porcelain",
    )
    bytes_before = main.read_bytes()

    result = evaluate_candidate_patch_from_snapshot(
        target,
        snapshot_patch("VALUE=1", "VALUE=2"),
        snapshot_patch("VALUE=2", "VALUE=3"),
    )

    assert result.status == STATUS_PASS
    assert result.passed
    assert result.changed_paths == ("src/main.txt",)
    assert main.read_bytes() == bytes_before
    assert git(
        target_repo,
        "status",
        "--porcelain",
    ) == status_before
    assert git(
        target_repo,
        "rev-parse",
        "HEAD",
    ).strip() == head


def test_invalid_snapshot_baseline_fails_before_worktree(
    tmp_path: Path,
    monkeypatch,
):
    harness = tmp_path / "invalid-harness"
    target_repo = tmp_path / "invalid-target"

    init_repo(harness, validator=True)
    init_repo(target_repo, validator=True)

    target = resolve_target(
        name="Droidra",
        harness_repo=harness,
        explicit_repo=target_repo,
    )

    import sophyane.evolution.target_evaluator as module

    monkeypatch.setattr(
        module,
        "create_target_worktree",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError(
                "invalid baseline created a worktree"
            )
        ),
    )

    result = evaluate_candidate_patch_from_snapshot(
        target,
        "not a patch",
        snapshot_patch("VALUE=2", "VALUE=3"),
    )

    assert result.status == STATUS_PATCH_INVALID
    assert "Baseline patch rejected" in result.message


def test_snapshot_candidate_policy_rejects_test_mutation(
    tmp_path: Path,
):
    harness = tmp_path / "policy-harness"
    target_repo = tmp_path / "policy-target"

    init_repo(harness, validator=True)
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

    main = target_repo / "src" / "main.txt"
    main.write_text("VALUE=2\n", encoding="utf-8")
    status_before = git(
        target_repo,
        "status",
        "--porcelain",
    )

    result = evaluate_candidate_patch_from_snapshot(
        target,
        snapshot_patch("VALUE=1", "VALUE=2"),
        snapshot_patch(
            "TEST=1",
            "TEST=2",
            relative="tests/test.txt",
        ),
    )

    assert result.status == STATUS_POLICY_REJECTED
    assert result.changed_paths == ("tests/test.txt",)
    assert git(
        target_repo,
        "status",
        "--porcelain",
    ) == status_before


def test_snapshot_validation_failure_cleans_worktree(
    tmp_path: Path,
    monkeypatch,
):
    harness = tmp_path / "failure-harness"
    target_repo = tmp_path / "failure-target"
    worktree_root = tmp_path / "snapshot-worktrees"

    init_repo(harness, validator=True)
    init_repo(target_repo, validator=True)

    wrapper = target_repo / "gradlew"
    wrapper.write_text(
        "#!/usr/bin/env sh\n"
        "exit 9\n",
        encoding="utf-8",
    )
    wrapper.chmod(wrapper.stat().st_mode | 0o111)
    git(target_repo, "add", "gradlew")
    git(target_repo, "commit", "--amend", "--no-edit")

    target = resolve_target(
        name="Droidra",
        harness_repo=harness,
        explicit_repo=target_repo,
    )

    main = target_repo / "src" / "main.txt"
    main.write_text("VALUE=2\n", encoding="utf-8")

    import sophyane.evolution.target_worktree as worktrees

    monkeypatch.setattr(
        worktrees,
        "default_worktree_root",
        lambda: worktree_root,
    )

    result = evaluate_candidate_patch_from_snapshot(
        target,
        snapshot_patch("VALUE=1", "VALUE=2"),
        snapshot_patch("VALUE=2", "VALUE=3"),
    )

    assert result.status == STATUS_VALIDATION_FAILED
    assert not result.passed
    assert (
        not worktree_root.exists()
        or not any(worktree_root.iterdir())
    )

def test_trusted_snapshot_api_preserves_existing_signatures() -> None:
    import inspect

    import sophyane.evolution.target_evaluator as module

    assert str(
        inspect.signature(
            module.evaluate_candidate_patch
        )
    ) == (
        "(target: 'TargetSpec', patch: 'str | bytes', *, "
        "timeout: 'int' = 300) -> 'CandidateEvaluation'"
    )

    assert str(
        inspect.signature(
            module.evaluate_candidate_patch_from_snapshot
        )
    ) == (
        "(target: 'TargetSpec', baseline_patch: 'str | bytes', "
        "candidate_patch: 'str | bytes', *, timeout: 'int' = 300) "
        "-> 'CandidateEvaluation'"
    )


def _trusted_request(
    family: str = "targeted",
    challenge_id: str = "trusted-fixture",
):
    from sophyane.evolution.red_queen_policy import (
        ChallengeRequest,
    )

    return ChallengeRequest(
        family=family,
        challenge_id=challenge_id,
        learned_from_epoch=1,
        evaluator_identity="trusted-fixture",
    )


def test_trusted_snapshot_runs_after_candidate_overlay_and_before_cleanup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import sophyane.evolution.target_evaluator as module
    from sophyane.evolution.trusted_supplemental_executor import (
        TrustedSupplementalResult,
    )

    harness = tmp_path / "trusted-harness"
    target_repo = tmp_path / "trusted-target"

    init_repo(harness, validator=True)
    init_repo(target_repo, validator=True)

    target = resolve_target(
        name="Droidra",
        harness_repo=harness,
        explicit_repo=target_repo,
    )

    main = target_repo / "src" / "main.txt"
    main.write_text("VALUE=2\n", encoding="utf-8")

    observed = []

    def trusted(worktree, requests, *, timeout):
        worktree = Path(worktree)
        observed.append(worktree)

        assert worktree.is_dir()
        assert (
            worktree / "src" / "main.txt"
        ).read_text(encoding="utf-8") == "VALUE=3\n"
        assert tuple(requests) == (
            _trusted_request(),
        )
        assert timeout == 300

        return TrustedSupplementalResult(
            status="PASS",
            evidence=(),
        )

    monkeypatch.setattr(
        module,
        "run_trusted_supplemental_challenges",
        trusted,
    )

    result = (
        module
        .evaluate_candidate_patch_from_snapshot_with_trusted_challenges(
            target,
            snapshot_patch("VALUE=1", "VALUE=2"),
            snapshot_patch("VALUE=2", "VALUE=3"),
            [_trusted_request()],
        )
    )

    assert result.candidate.status == module.STATUS_PASS
    assert result.supplemental is not None
    assert result.supplemental.status == "PASS"
    assert result.passed
    assert len(observed) == 1
    assert not observed[0].exists()
    assert main.read_text(encoding="utf-8") == "VALUE=2\n"


@pytest.mark.parametrize(
    "trusted_status",
    ["FAIL", "INVALID"],
)
def test_trusted_failure_cannot_upgrade_candidate(
    tmp_path: Path,
    monkeypatch,
    trusted_status: str,
) -> None:
    import sophyane.evolution.target_evaluator as module
    from sophyane.evolution.trusted_supplemental_executor import (
        TrustedSupplementalResult,
    )

    harness = tmp_path / f"{trusted_status}-harness"
    target_repo = tmp_path / f"{trusted_status}-target"

    init_repo(harness, validator=True)
    init_repo(target_repo, validator=True)

    target = resolve_target(
        name="Droidra",
        harness_repo=harness,
        explicit_repo=target_repo,
    )

    (target_repo / "src" / "main.txt").write_text(
        "VALUE=2\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "run_trusted_supplemental_challenges",
        lambda *_args, **_kwargs: TrustedSupplementalResult(
            status=trusted_status,
            evidence=(),
        ),
    )

    result = (
        module
        .evaluate_candidate_patch_from_snapshot_with_trusted_challenges(
            target,
            snapshot_patch("VALUE=1", "VALUE=2"),
            snapshot_patch("VALUE=2", "VALUE=3"),
            [_trusted_request()],
        )
    )

    assert result.candidate.status == module.STATUS_PASS
    assert result.supplemental is not None
    assert result.supplemental.status == trusted_status
    assert not result.passed


def test_ordinary_failure_skips_trusted_execution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import sophyane.evolution.target_evaluator as module

    harness = tmp_path / "ordinary-failure-harness"
    target_repo = tmp_path / "ordinary-failure-target"

    init_repo(harness, validator=True)
    init_repo(target_repo, validator=True)

    wrapper = target_repo / "gradlew"
    wrapper.write_text(
        "#!/usr/bin/env sh\nexit 7\n",
        encoding="utf-8",
    )
    git(target_repo, "add", "gradlew")
    git(target_repo, "commit", "--amend", "--no-edit")

    target = resolve_target(
        name="Droidra",
        harness_repo=harness,
        explicit_repo=target_repo,
    )

    (target_repo / "src" / "main.txt").write_text(
        "VALUE=2\n",
        encoding="utf-8",
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError(
            "trusted executor ran after ordinary failure"
        )

    monkeypatch.setattr(
        module,
        "run_trusted_supplemental_challenges",
        forbidden,
    )

    result = (
        module
        .evaluate_candidate_patch_from_snapshot_with_trusted_challenges(
            target,
            snapshot_patch("VALUE=1", "VALUE=2"),
            snapshot_patch("VALUE=2", "VALUE=3"),
            [_trusted_request()],
        )
    )

    assert result.candidate.status == (
        module.STATUS_VALIDATION_FAILED
    )
    assert result.supplemental is None
    assert not result.passed


@pytest.mark.parametrize(
    "requests",
    [
        "targeted",
        [object()],
    ],
)
def test_invalid_trusted_requests_fail_before_worktree(
    tmp_path: Path,
    monkeypatch,
    requests,
) -> None:
    import sophyane.evolution.target_evaluator as module

    monkeypatch.setattr(
        module,
        "create_target_worktree",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("worktree was created")
        ),
    )

    with pytest.raises(ValueError):
        (
            module
            .evaluate_candidate_patch_from_snapshot_with_trusted_challenges(
                object(),
                "baseline",
                "candidate",
                requests,
            )
        )


def test_duplicate_trusted_requests_fail_before_worktree(
    monkeypatch,
) -> None:
    import sophyane.evolution.target_evaluator as module
    from sophyane.evolution.red_queen_policy import (
        ChallengeRequest,
    )

    first = _trusted_request()
    duplicate = ChallengeRequest(
        family="security",
        challenge_id=first.challenge_id,
        learned_from_epoch=1,
        evaluator_identity="trusted-fixture",
    )

    monkeypatch.setattr(
        module,
        "create_target_worktree",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("worktree was created")
        ),
    )

    with pytest.raises(ValueError, match="duplicate"):
        (
            module
            .evaluate_candidate_patch_from_snapshot_with_trusted_challenges(
                object(),
                "baseline",
                "candidate",
                [first, duplicate],
            )
        )


def test_trusted_executor_exception_still_cleans_worktree(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import sophyane.evolution.target_evaluator as module

    harness = tmp_path / "exception-harness"
    target_repo = tmp_path / "exception-target"

    init_repo(harness, validator=True)
    init_repo(target_repo, validator=True)

    target = resolve_target(
        name="Droidra",
        harness_repo=harness,
        explicit_repo=target_repo,
    )

    (target_repo / "src" / "main.txt").write_text(
        "VALUE=2\n",
        encoding="utf-8",
    )

    observed = []

    def broken(worktree, *_args, **_kwargs):
        observed.append(Path(worktree))
        raise RuntimeError("trusted executor failed")

    monkeypatch.setattr(
        module,
        "run_trusted_supplemental_challenges",
        broken,
    )

    result = (
        module
        .evaluate_candidate_patch_from_snapshot_with_trusted_challenges(
            target,
            snapshot_patch("VALUE=1", "VALUE=2"),
            snapshot_patch("VALUE=2", "VALUE=3"),
            [_trusted_request()],
        )
    )

    assert result.candidate.status == module.STATUS_INTERNAL_ERROR
    assert result.supplemental is None
    assert not result.passed
    assert len(observed) == 1
    assert not observed[0].exists()

def test_clean_trusted_api_preserves_existing_signature() -> None:
    import inspect

    import sophyane.evolution.target_evaluator as module

    assert str(
        inspect.signature(
            module.evaluate_candidate_patch
        )
    ) == (
        "(target: 'TargetSpec', patch: 'str | bytes', *, "
        "timeout: 'int' = 300) -> 'CandidateEvaluation'"
    )

    assert str(
        inspect.signature(
            module.evaluate_candidate_patch_with_trusted_challenges
        )
    ) == (
        "(target: 'TargetSpec', patch: 'str | bytes', "
        "requests: 'Iterable[ChallengeRequest]', *, "
        "timeout: 'int' = 300) -> 'TrustedCandidateEvaluation'"
    )


def test_clean_trusted_runs_after_candidate_and_before_cleanup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import sophyane.evolution.target_evaluator as module
    from sophyane.evolution.trusted_supplemental_executor import (
        TrustedSupplementalResult,
    )

    harness = tmp_path / "clean-trusted-harness"
    target_repo = tmp_path / "clean-trusted-target"

    init_repo(harness, validator=True)
    init_repo(target_repo, validator=True)

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

    head_before = git(
        target_repo,
        "rev-parse",
        "HEAD",
    )
    status_before = git(
        target_repo,
        "status",
        "--porcelain",
    )
    bytes_before = (
        target_repo / "src" / "main.txt"
    ).read_bytes()

    observed = []

    def trusted(worktree, requests, *, timeout):
        worktree = Path(worktree)
        observed.append(worktree)

        assert worktree.is_dir()
        assert (
            worktree / "src" / "main.txt"
        ).read_text(encoding="utf-8") == "VALUE=3\n"
        assert tuple(requests) == (
            _trusted_request(),
        )
        assert timeout == 300

        return TrustedSupplementalResult(
            status="PASS",
            evidence=(),
        )

    monkeypatch.setattr(
        module,
        "run_trusted_supplemental_challenges",
        trusted,
    )

    result = (
        module
        .evaluate_candidate_patch_with_trusted_challenges(
            target,
            patch,
            [_trusted_request()],
        )
    )

    assert result.candidate.status == module.STATUS_PASS
    assert result.supplemental is not None
    assert result.supplemental.status == "PASS"
    assert result.passed
    assert len(observed) == 1
    assert not observed[0].exists()

    assert (
        target_repo / "src" / "main.txt"
    ).read_bytes() == bytes_before
    assert git(
        target_repo,
        "rev-parse",
        "HEAD",
    ) == head_before
    assert git(
        target_repo,
        "status",
        "--porcelain",
    ) == status_before


@pytest.mark.parametrize(
    "trusted_status",
    ["FAIL", "INVALID"],
)
def test_clean_trusted_failure_cannot_upgrade_candidate(
    tmp_path: Path,
    monkeypatch,
    trusted_status: str,
) -> None:
    import sophyane.evolution.target_evaluator as module
    from sophyane.evolution.trusted_supplemental_executor import (
        TrustedSupplementalResult,
    )

    harness = tmp_path / f"clean-{trusted_status}-harness"
    target_repo = tmp_path / f"clean-{trusted_status}-target"

    init_repo(harness, validator=True)
    init_repo(target_repo, validator=True)

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

    monkeypatch.setattr(
        module,
        "run_trusted_supplemental_challenges",
        lambda *_args, **_kwargs: TrustedSupplementalResult(
            status=trusted_status,
            evidence=(),
        ),
    )

    result = (
        module
        .evaluate_candidate_patch_with_trusted_challenges(
            target,
            patch,
            [_trusted_request()],
        )
    )

    assert result.candidate.status == module.STATUS_PASS
    assert result.supplemental is not None
    assert result.supplemental.status == trusted_status
    assert not result.passed


def test_clean_ordinary_failure_skips_trusted_execution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import sophyane.evolution.target_evaluator as module

    harness = tmp_path / "clean-failure-harness"
    target_repo = tmp_path / "clean-failure-target"

    init_repo(harness, validator=True)
    init_repo(target_repo, validator=True)

    wrapper = target_repo / "gradlew"
    wrapper.write_text(
        "#!/usr/bin/env sh\nexit 8\n",
        encoding="utf-8",
    )
    git(target_repo, "add", "gradlew")
    git(target_repo, "commit", "--amend", "--no-edit")

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

    def forbidden(*_args, **_kwargs):
        raise AssertionError(
            "trusted executor ran after ordinary failure"
        )

    monkeypatch.setattr(
        module,
        "run_trusted_supplemental_challenges",
        forbidden,
    )

    result = (
        module
        .evaluate_candidate_patch_with_trusted_challenges(
            target,
            patch,
            [_trusted_request()],
        )
    )

    assert result.candidate.status == (
        module.STATUS_VALIDATION_FAILED
    )
    assert result.supplemental is None
    assert not result.passed


def test_clean_invalid_requests_fail_before_worktree(
    monkeypatch,
) -> None:
    import sophyane.evolution.target_evaluator as module

    monkeypatch.setattr(
        module,
        "create_target_worktree",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("worktree was created")
        ),
    )

    with pytest.raises(ValueError):
        (
            module
            .evaluate_candidate_patch_with_trusted_challenges(
                object(),
                "candidate",
                [object()],
            )
        )


def test_clean_trusted_exception_still_cleans_worktree(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import sophyane.evolution.target_evaluator as module

    harness = tmp_path / "clean-exception-harness"
    target_repo = tmp_path / "clean-exception-target"

    init_repo(harness, validator=True)
    init_repo(target_repo, validator=True)

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

    observed = []

    def broken(worktree, *_args, **_kwargs):
        observed.append(Path(worktree))
        raise RuntimeError("trusted executor failed")

    monkeypatch.setattr(
        module,
        "run_trusted_supplemental_challenges",
        broken,
    )

    result = (
        module
        .evaluate_candidate_patch_with_trusted_challenges(
            target,
            patch,
            [_trusted_request()],
        )
    )

    assert result.candidate.status == module.STATUS_INTERNAL_ERROR
    assert result.supplemental is None
    assert not result.passed
    assert len(observed) == 1
    assert not observed[0].exists()


def test_verified_execution_evidence_adapter_preserves_structured_history(monkeypatch, tmp_path):
    from sophyane.evolution.evidence_pipeline import EvidenceStore
    rows = [{
        "event_key": "event-a", "objective_hash": "hash-a",
        "original_objective": "build a generic artifact",
        "status": "succeeded", "verification_state": "verified",
        "verification_evidence": [{"ok": True, "command": ["check"]}],
        "accepted": True, "repository_identity": "repo-alpha",
        "provider_identity": "provider-a", "capability_class": "external_harness",
    }, {
        "event_key": "event-a", "objective_hash": "hash-a",
        "status": "succeeded", "verification_state": "verified",
        "verification_evidence": [{"ok": True}], "accepted": True,
    }]
    monkeypatch.setattr("sophyane.sli_learner.read_verified_history", lambda **kwargs: rows)
    evidence = EvidenceStore(tmp_path).collect_verified_execution_evidence()
    assert len(evidence) == 1
    assert evidence[0]["objective_hash"] == "hash-a"
    assert evidence[0]["repository_identity"] == "repo-alpha"
    assert evidence[0]["provider_identity"] == "provider-a"
    assert evidence[0]["verification_evidence"][0]["ok"] is True


@pytest.mark.parametrize("row", [
    {"accepted": False, "status": "succeeded", "verification_state": "verified"},
    {"accepted": True, "status": "failed", "verification_state": "verified"},
    {"accepted": True, "status": "succeeded", "verification_state": "verification_failed"},
    {"accepted": True, "status": "succeeded", "verification_state": "verified", "verification_evidence": []},
    {"accepted": True, "status": "succeeded", "verification_state": "verified", "verification_evidence": [{"ok": True}], "source": "mode3-rsi"},
    {"accepted": True, "status": "succeeded", "verification_state": "verified", "verification_evidence": [{"ok": True}], "transport_failure": True},
    {"accepted": True, "status": "succeeded", "verification_state": "verified", "verification_evidence": [{"ok": True}], "safety_failure": True},
    {"accepted": True, "status": "succeeded", "verification_state": "verified", "verification_evidence": [{"ok": True}], "approval_failure": True},
    {"accepted": True, "status": "succeeded", "verification_state": "verified", "verification_evidence": [{"ok": True}], "permission_failure": True},
])
def test_verified_execution_evidence_adapter_rejects_untrusted_or_ambiguous(monkeypatch, tmp_path, row):
    from sophyane.evolution.evidence_pipeline import EvidenceStore
    payload = {"event_key": "bad", "verification_evidence": [{"ok": True}], **row}
    monkeypatch.setattr("sophyane.sli_learner.read_verified_history", lambda **kwargs: [payload])
    assert EvidenceStore(tmp_path).verified_execution_evidence() == []


def test_verified_execution_evidence_adapter_fails_neutral_and_is_read_only(monkeypatch, tmp_path):
    from sophyane.evolution.evidence_pipeline import EvidenceStore
    monkeypatch.setattr("sophyane.sli_learner.read_verified_history", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("missing")))
    store = EvidenceStore(tmp_path)
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    assert store.collect_verified_execution_evidence() == []
    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    assert before == after


def test_verified_execution_evidence_is_observational(monkeypatch, tmp_path):
    from sophyane.evolution.evidence_pipeline import EvidenceStore
    calls = {"reader": 0, "provider": 0, "race": 0, "candidate": 0, "mutation": 0, "promotion": 0}
    def reader(**kwargs):
        calls["reader"] += 1
        return [{
            "event_key": "observed", "accepted": True, "status": "completed",
            "verification_state": "verified", "verification_evidence": [{"ok": True}],
            "objective_hash": "objective", "provider_identity": "provider",
            "capability_class": "capability",
        }]
    monkeypatch.setattr("sophyane.sli_learner.read_verified_history", reader)
    result = EvidenceStore(tmp_path).verified_execution_evidence()
    assert len(result) == 1
    assert calls == {"reader": 1, "provider": 0, "race": 0, "candidate": 0, "mutation": 0, "promotion": 0}
