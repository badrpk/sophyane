from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import sophyane.competitive_coding_phase2 as phase2
from sophyane.evolution.target_evaluator import (
    CandidateEvaluation,
    STATUS_PASS,
)


VALID_PATCH = """diff --git a/src/main.py b/src/main.py
--- a/src/main.py
+++ b/src/main.py
@@ -1 +1 @@
-VALUE = 2
+VALUE = 3
"""


def init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "sophyane"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-q"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Phase Two"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "config",
            "user.email",
            "phase2@example.invalid",
        ],
        cwd=repo,
        check=True,
    )

    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )
    (repo / "unrelated.py").write_text(
        "UNRELATED = 1\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "."],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-qm", "fixture"],
        cwd=repo,
        check=True,
    )
    return repo


def passed_evaluation() -> CandidateEvaluation:
    return CandidateEvaluation(
        status=STATUS_PASS,
        target_name="sophyane",
        source_head="abc",
        changed_paths=("src/main.py",),
        validator_checks=(),
        validator_runs=(),
        message="passed",
    )


def test_dirty_baseline_uses_snapshot_evaluator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = init_repo(tmp_path)
    (repo / "src" / "main.py").write_text(
        "VALUE = 2\n",
        encoding="utf-8",
    )
    (repo / "unrelated.py").write_text(
        "UNRELATED = 2\n",
        encoding="utf-8",
    )

    snapshot_calls = []
    clean_calls = []

    monkeypatch.setattr(
        phase2,
        "evaluate_candidate_patch_from_snapshot",
        lambda target, baseline, candidate, timeout: (
            snapshot_calls.append(
                (target, baseline, candidate, timeout)
            )
            or passed_evaluation()
        ),
    )
    monkeypatch.setattr(
        phase2,
        "evaluate_candidate_patch",
        lambda *args, **kwargs: (
            clean_calls.append((args, kwargs))
            or passed_evaluation()
        ),
    )

    before_status = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        cwd=repo,
        capture_output=True,
        check=True,
    ).stdout

    result = phase2.run_competitive_evaluation(
        objective="repair",
        repository=repo,
        baseline_paths=["src/main.py"],
        candidate_provider=lambda _: VALID_PATCH,
    )

    assert len(snapshot_calls) == 2
    assert not clean_calls
    assert "src/main.py" in result.baseline_patch
    assert "unrelated.py" not in result.baseline_patch
    assert result.status == "fail_closed"
    assert result.winner is None
    assert result.missing_boundary == (
        "trusted_held_out_security_red_queen_gate_adapter"
    )
    assert all(
        candidate.passed
        for candidate in result.candidates
    )

    after_status = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        cwd=repo,
        capture_output=True,
        check=True,
    ).stdout
    assert after_status == before_status


def test_clean_baseline_uses_clean_evaluator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = init_repo(tmp_path)
    calls = []

    monkeypatch.setattr(
        phase2,
        "evaluate_candidate_patch",
        lambda target, patch, timeout: (
            calls.append((target, patch, timeout))
            or passed_evaluation()
        ),
    )

    result = phase2.run_competitive_evaluation(
        objective="repair",
        repository=repo,
        baseline_paths=["src/main.py"],
        candidate_provider=lambda _: VALID_PATCH,
    )

    assert result.baseline_patch == ""
    assert len(calls) == 2
    assert len(result.candidates) == 2


def test_invalid_proposal_is_preserved_and_not_evaluated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = init_repo(tmp_path)
    responses = iter([VALID_PATCH, "not a patch"])
    calls = []

    monkeypatch.setattr(
        phase2,
        "evaluate_candidate_patch",
        lambda *args, **kwargs: (
            calls.append((args, kwargs))
            or passed_evaluation()
        ),
    )

    result = phase2.run_competitive_evaluation(
        objective="repair",
        repository=repo,
        baseline_paths=["src/main.py"],
        candidate_provider=lambda _: next(responses),
    )

    assert len(result.candidates) == 2
    assert len(calls) == 1
    assert result.candidates[0].proposal_valid
    assert not result.candidates[1].proposal_valid
    assert result.candidates[1].evaluation_status == (
        "NOT_EVALUATED"
    )
    assert result.candidates[1].proposal_rejection_reason


def test_requires_explicit_bounded_baseline_paths(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)

    with pytest.raises(
        phase2.CompetitiveEvaluationError,
        match="at least one",
    ):
        phase2.run_competitive_evaluation(
            objective="repair",
            repository=repo,
            baseline_paths=[],
            candidate_provider=lambda _: VALID_PATCH,
        )

    with pytest.raises(
        phase2.CompetitiveEvaluationError,
        match="baseline construction",
    ):
        phase2.run_competitive_evaluation(
            objective="repair",
            repository=repo,
            baseline_paths=["../escape.py"],
            candidate_provider=lambda _: VALID_PATCH,
        )


def test_phase1_api_remains_unchanged() -> None:
    import inspect

    from sophyane.competitive_coding import (
        run_competitive_coding,
    )

    assert list(
        inspect.signature(
            run_competitive_coding
        ).parameters
    ) == [
        "objective",
        "repository",
        "candidate_provider",
        "candidate_count",
        "apply_winner",
        "progress",
    ]

def trusted_request(
    family: str = "targeted",
    challenge_id: str = "trusted-phase2",
):
    from sophyane.evolution.red_queen_policy import (
        ChallengeRequest,
    )

    return ChallengeRequest(
        family=family,
        challenge_id=challenge_id,
        learned_from_epoch=1,
        evaluator_identity="phase2-fixture",
    )


def trusted_evidence(
    *,
    family: str = "targeted",
    passed: bool = True,
):
    from sophyane.evolution.trusted_supplemental_executor import (
        TrustedSupplementalEvidence,
    )

    return TrustedSupplementalEvidence(
        family=family,
        challenge_id=f"trusted::{family}",
        evaluator_identity="phase2-fixture",
        test_path=(
            "tests/red_queen/"
            f"test_{family}_supplemental.py"
        ),
        executed=True,
        passed=passed,
        returncode=0 if passed else 1,
        timed_out=False,
        elapsed_seconds=0.01,
        stdout="trusted stdout",
        stderr="",
        rejection_reason=(
            None
            if passed
            else "supplemental test failed"
        ),
    )


def trusted_composite(
    status: str = "PASS",
    *,
    candidate_status: str = "PASS",
):
    from sophyane.evolution.target_evaluator import (
        CandidateEvaluation,
        TrustedCandidateEvaluation,
    )
    from sophyane.evolution.trusted_supplemental_executor import (
        TrustedSupplementalResult,
    )

    candidate = CandidateEvaluation(
        status=candidate_status,
        target_name="sophyane",
        source_head="fixture-head",
        changed_paths=("src/main.py",),
        validator_checks=(),
        validator_runs=(),
        message="ordinary evaluation",
    )

    supplemental = (
        None
        if status == "NOT_EXECUTED"
        else TrustedSupplementalResult(
            status=status,
            evidence=(
                trusted_evidence(
                    passed=status == "PASS"
                ),
            ),
        )
    )

    return TrustedCandidateEvaluation(
        candidate=candidate,
        supplemental=supplemental,
    )


def test_trusted_phase2_exact_signature() -> None:
    import inspect

    assert str(
        inspect.signature(
            phase2.run_competitive_evaluation
        )
    ) == (
        "(*, objective: 'str', repository: 'Path', "
        "baseline_paths: 'Iterable[str]', candidate_provider, "
        "target_name: 'str' = 'sophyane', "
        "candidate_count: 'int' = 2, "
        "progress: 'Callable[[str], None] | None' = None, "
        "timeout: 'int' = 300) -> 'CompetitiveEvaluationResult'"
    )

    assert str(
        inspect.signature(
            phase2.run_competitive_trusted_evaluation
        )
    ) == (
        "(*, objective: 'str', repository: 'Path', "
        "baseline_paths: 'Iterable[str]', candidate_provider, "
        "challenge_requests: 'Iterable[ChallengeRequest]', "
        "target_name: 'str' = 'sophyane', "
        "candidate_count: 'int' = 2, "
        "progress: 'Callable[[str], None] | None' = None, "
        "timeout: 'int' = 300) -> 'CompetitiveEvaluationResult'"
    )


@pytest.mark.parametrize(
    "requests",
    [
        [],
        "targeted",
        [object()],
    ],
)
def test_invalid_trusted_requests_fail_before_provider(
    tmp_path: Path,
    requests,
) -> None:
    calls = []

    with pytest.raises(
        phase2.CompetitiveEvaluationError
    ):
        phase2.run_competitive_trusted_evaluation(
            objective="repair",
            repository=tmp_path,
            baseline_paths=["src/main.py"],
            candidate_provider=lambda prompt: calls.append(
                prompt
            ),
            challenge_requests=requests,
        )

    assert calls == []


def test_duplicate_trusted_requests_fail_before_provider(
    tmp_path: Path,
) -> None:
    from sophyane.evolution.red_queen_policy import (
        ChallengeRequest,
    )

    first = trusted_request()
    duplicate = ChallengeRequest(
        family="security",
        challenge_id=first.challenge_id,
        learned_from_epoch=1,
        evaluator_identity="phase2-fixture",
    )
    calls = []

    with pytest.raises(
        phase2.CompetitiveEvaluationError,
        match="duplicate",
    ):
        phase2.run_competitive_trusted_evaluation(
            objective="repair",
            repository=tmp_path,
            baseline_paths=["src/main.py"],
            candidate_provider=lambda prompt: calls.append(
                prompt
            ),
            challenge_requests=[
                first,
                duplicate,
            ],
        )

    assert calls == []


def test_dirty_baseline_uses_trusted_snapshot_for_every_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = init_repo(tmp_path)

    (repo / "src" / "main.py").write_text(
        "VALUE = 2\n",
        encoding="utf-8",
    )
    (repo / "unrelated.py").write_text(
        "UNRELATED = 2\n",
        encoding="utf-8",
    )
    (repo / "unrelated-new.py").write_text(
        "UNTRACKED = 1\n",
        encoding="utf-8",
    )

    before_status = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        cwd=repo,
        capture_output=True,
        check=True,
    ).stdout
    before_main = (
        repo / "src" / "main.py"
    ).read_bytes()

    request = trusted_request()
    calls = []

    def snapshot(
        target,
        baseline,
        patch,
        requests,
        *,
        timeout,
    ):
        calls.append(
            (
                target,
                baseline,
                patch,
                requests,
                timeout,
            )
        )
        return trusted_composite("PASS")

    monkeypatch.setattr(
        phase2,
        "evaluate_candidate_patch_from_snapshot_with_trusted_challenges",
        snapshot,
    )
    monkeypatch.setattr(
        phase2,
        "evaluate_candidate_patch_with_trusted_challenges",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError(
                "clean trusted evaluator was used"
            )
        ),
    )

    result = phase2.run_competitive_trusted_evaluation(
        objective="repair",
        repository=repo,
        baseline_paths=["src/main.py"],
        candidate_provider=lambda _: VALID_PATCH,
        challenge_requests=[request],
    )

    assert len(calls) == 2
    assert calls[0][3] is calls[1][3]
    assert calls[0][3] == (request,)
    assert all(call[4] == 300 for call in calls)

    assert "src/main.py" in result.baseline_patch
    assert "unrelated.py" not in result.baseline_patch
    assert "unrelated-new.py" not in result.baseline_patch

    assert all(
        item.trusted_status == "PASS"
        and item.trusted_passed
        and item.passed
        and len(item.trusted_evidence) == 1
        for item in result.candidates
    )

    assert result.status == "fail_closed"
    assert result.missing_boundary == (
        "trusted_candidate_ranking_and_approval"
    )
    assert result.winner is None

    assert (
        repo / "src" / "main.py"
    ).read_bytes() == before_main
    assert subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        cwd=repo,
        capture_output=True,
        check=True,
    ).stdout == before_status


def test_clean_baseline_uses_trusted_clean_evaluator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = init_repo(tmp_path)
    request = trusted_request()
    calls = []

    def clean(
        target,
        patch,
        requests,
        *,
        timeout,
    ):
        calls.append(
            (
                target,
                patch,
                requests,
                timeout,
            )
        )
        return trusted_composite("PASS")

    monkeypatch.setattr(
        phase2,
        "evaluate_candidate_patch_with_trusted_challenges",
        clean,
    )
    monkeypatch.setattr(
        phase2,
        "evaluate_candidate_patch_from_snapshot_with_trusted_challenges",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError(
                "snapshot trusted evaluator was used"
            )
        ),
    )

    result = phase2.run_competitive_trusted_evaluation(
        objective="repair",
        repository=repo,
        baseline_paths=["src/main.py"],
        candidate_provider=lambda _: VALID_PATCH,
        challenge_requests=[request],
    )

    assert result.baseline_patch == ""
    assert len(calls) == 2
    assert calls[0][2] is calls[1][2]
    assert calls[0][2] == (request,)
    assert all(item.passed for item in result.candidates)


@pytest.mark.parametrize(
    "trusted_status",
    ["FAIL", "INVALID"],
)
def test_trusted_failure_evidence_is_preserved_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    trusted_status: str,
) -> None:
    repo = init_repo(tmp_path)

    monkeypatch.setattr(
        phase2,
        "evaluate_candidate_patch_with_trusted_challenges",
        lambda *_args, **_kwargs: trusted_composite(
            trusted_status
        ),
    )

    result = phase2.run_competitive_trusted_evaluation(
        objective="repair",
        repository=repo,
        baseline_paths=["src/main.py"],
        candidate_provider=lambda _: VALID_PATCH,
        challenge_requests=[trusted_request()],
    )

    assert all(
        item.evaluation_status == "PASS"
        and item.trusted_status == trusted_status
        and not item.trusted_passed
        and not item.passed
        and item.trusted_evidence
        for item in result.candidates
    )


def test_ordinary_failure_records_not_executed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = init_repo(tmp_path)

    monkeypatch.setattr(
        phase2,
        "evaluate_candidate_patch_with_trusted_challenges",
        lambda *_args, **_kwargs: trusted_composite(
            "NOT_EXECUTED",
            candidate_status="VALIDATION_FAILED",
        ),
    )

    result = phase2.run_competitive_trusted_evaluation(
        objective="repair",
        repository=repo,
        baseline_paths=["src/main.py"],
        candidate_provider=lambda _: VALID_PATCH,
        challenge_requests=[trusted_request()],
    )

    assert all(
        item.evaluation_status == "VALIDATION_FAILED"
        and item.trusted_status == "NOT_EXECUTED"
        and not item.trusted_passed
        and item.trusted_evidence == ()
        and not item.passed
        for item in result.candidates
    )


def test_invalid_proposal_is_not_trusted_evaluated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = init_repo(tmp_path)
    responses = iter(
        [
            VALID_PATCH,
            "not a patch",
        ]
    )
    calls = []

    monkeypatch.setattr(
        phase2,
        "evaluate_candidate_patch_with_trusted_challenges",
        lambda *_args, **_kwargs: (
            calls.append(True)
            or trusted_composite("PASS")
        ),
    )

    result = phase2.run_competitive_trusted_evaluation(
        objective="repair",
        repository=repo,
        baseline_paths=["src/main.py"],
        candidate_provider=lambda _: next(responses),
        challenge_requests=[trusted_request()],
    )

    assert calls == [True]
    assert result.candidates[0].trusted_status == "PASS"
    assert result.candidates[1].trusted_status == (
        "NOT_EVALUATED"
    )
    assert not result.candidates[1].passed


def test_candidate_exception_does_not_stop_later_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = init_repo(tmp_path)
    calls = []

    def evaluate(*_args, **_kwargs):
        calls.append(len(calls) + 1)

        if len(calls) == 1:
            raise RuntimeError("first candidate failed")

        return trusted_composite("PASS")

    monkeypatch.setattr(
        phase2,
        "evaluate_candidate_patch_with_trusted_challenges",
        evaluate,
    )

    result = phase2.run_competitive_trusted_evaluation(
        objective="repair",
        repository=repo,
        baseline_paths=["src/main.py"],
        candidate_provider=lambda _: VALID_PATCH,
        challenge_requests=[trusted_request()],
    )

    assert calls == [1, 2]
    assert result.candidates[0].evaluation_status == (
        phase2.STATUS_INTERNAL_ERROR
    )
    assert result.candidates[0].trusted_status == (
        "NOT_EXECUTED"
    )
    assert not result.candidates[0].passed
    assert result.candidates[1].trusted_status == "PASS"
    assert result.candidates[1].passed

def test_phase2_evidence_binding_fields_are_compatible() -> None:
    import hashlib
    from dataclasses import fields

    candidate_fields = {
        item.name: item
        for item in fields(
            phase2.CompetitiveEvaluationCandidate
        )
    }
    result_fields = {
        item.name: item
        for item in fields(
            phase2.CompetitiveEvaluationResult
        )
    }

    assert candidate_fields["patch"].default == ""
    assert candidate_fields["patch_sha256"].default == ""
    assert candidate_fields["source_head"].default == ""
    assert result_fields["source_head"].default == ""
    assert (
        result_fields["baseline_patch_sha256"].default
        == ""
    )

    assert phase2._patch_digest("") == hashlib.sha256(
        b""
    ).hexdigest()


def test_phase2_binds_exact_patch_head_and_baseline_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib

    repo = init_repo(tmp_path)

    (repo / "src" / "main.py").write_text(
        "VALUE = 2\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        phase2,
        "evaluate_candidate_patch_from_snapshot_with_trusted_challenges",
        lambda *_args, **_kwargs: trusted_composite("PASS"),
    )

    result = phase2.run_competitive_trusted_evaluation(
        objective="repair",
        repository=repo,
        baseline_paths=["src/main.py"],
        candidate_provider=lambda _: VALID_PATCH,
        challenge_requests=[trusted_request()],
    )

    expected_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    assert result.source_head == expected_head
    assert result.baseline_patch_sha256 == (
        hashlib.sha256(
            result.baseline_patch.encode("utf-8")
        ).hexdigest()
    )

    for candidate in result.candidates:
        assert candidate.patch == VALID_PATCH
        assert candidate.patch_sha256 == hashlib.sha256(
            VALID_PATCH.encode("utf-8")
        ).hexdigest()
        assert candidate.source_head == expected_head


def test_invalid_proposal_patch_is_also_cryptographically_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib

    repo = init_repo(tmp_path)
    invalid = "not a patch"
    responses = iter(
        [
            VALID_PATCH,
            invalid,
        ]
    )

    monkeypatch.setattr(
        phase2,
        "evaluate_candidate_patch_with_trusted_challenges",
        lambda *_args, **_kwargs: trusted_composite("PASS"),
    )

    result = phase2.run_competitive_trusted_evaluation(
        objective="repair",
        repository=repo,
        baseline_paths=["src/main.py"],
        candidate_provider=lambda _: next(responses),
        challenge_requests=[trusted_request()],
    )

    rejected = result.candidates[1]

    assert not rejected.proposal_valid
    assert rejected.patch == invalid
    assert rejected.patch_sha256 == hashlib.sha256(
        invalid.encode("utf-8")
    ).hexdigest()
    assert rejected.source_head == result.source_head


def test_repository_head_drift_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = init_repo(tmp_path)
    observed = iter(
        [
            "head-before",
            "head-after",
        ]
    )

    monkeypatch.setattr(
        phase2,
        "target_head",
        lambda _target: next(observed),
    )
    monkeypatch.setattr(
        phase2,
        "evaluate_candidate_patch_with_trusted_challenges",
        lambda *_args, **_kwargs: trusted_composite("PASS"),
    )

    with pytest.raises(
        phase2.CompetitiveEvaluationError,
        match="HEAD changed",
    ):
        phase2.run_competitive_trusted_evaluation(
            objective="repair",
            repository=repo,
            baseline_paths=["src/main.py"],
            candidate_provider=lambda _: VALID_PATCH,
            challenge_requests=[trusted_request()],
        )
