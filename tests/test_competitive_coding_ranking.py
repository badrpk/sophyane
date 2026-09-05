from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from sophyane.competitive_coding_phase2 import (
    CompetitiveEvaluationCandidate,
    CompetitiveEvaluationResult,
)
from sophyane.competitive_coding_ranking import (
    CompetitiveRankingError,
    rank_competitive_evaluation,
)
from sophyane.evolution.trusted_supplemental_executor import TrustedSupplementalEvidence
from sophyane.scoped_candidate_diff import candidate_diff_for_paths


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-C", str(repo), *args), check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ).stdout.strip()


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def fixture_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    (repo / "app.py").write_text("VALUE = 1\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    (repo / "app.py").write_text("VALUE = 2\n")
    return repo


def evidence(**changes: object) -> TrustedSupplementalEvidence:
    values = dict(
        family="targeted", challenge_id="c1", evaluator_identity="judge",
        test_path="tests/red_queen/test_targeted_supplemental.py",
        executed=True, passed=True, returncode=0, timed_out=False,
        elapsed_seconds=.1, stdout="ok", stderr="", rejection_reason=None,
    )
    values.update(changes)
    return TrustedSupplementalEvidence(**values)


def candidate(repo: Path, name: str = "only", **changes: object) -> CompetitiveEvaluationCandidate:
    patch = changes.pop("patch", f"patch-{name}")
    values = dict(
        candidate_id=name, proposal_valid=True, proposal_rejection_reason="",
        evaluation_status="PASS", evaluation_message="ok", changed_paths=("app.py",),
        validators=("tests",), passed=True, trusted_status="PASS", trusted_passed=True,
        trusted_evidence=(evidence(),), patch=patch, patch_sha256=digest(patch),
        source_head=git(repo, "rev-parse", "HEAD"),
    )
    values.update(changes)
    return CompetitiveEvaluationCandidate(**values)


def result(repo: Path, candidates: tuple[CompetitiveEvaluationCandidate, ...]) -> CompetitiveEvaluationResult:
    baseline = candidate_diff_for_paths(repo, ("app.py",))
    return CompetitiveEvaluationResult(
        objective="repair", repository=repo.resolve(), target_name="sophyane",
        baseline_paths=("app.py",), baseline_patch=baseline, txq_policy=None,
        candidates=candidates, status="fail_closed",
        missing_boundary="trusted_candidate_ranking_and_approval", winner=None,
        source_head=git(repo, "rev-parse", "HEAD"),
        baseline_patch_sha256=digest(baseline),
    )

def test_empty_patch_binding_must_still_have_exact_digest(
    tmp_path: Path,
) -> None:
    repo = fixture_repo(tmp_path)
    item = candidate(
        repo,
        patch="",
        patch_sha256="",
    )

    with pytest.raises(
        CompetitiveRankingError,
        match="patch digest mismatch",
    ):
        rank_competitive_evaluation(
            result(repo, (item,))
        )


def test_empty_patch_with_correct_digest_is_bound_but_ineligible(
    tmp_path: Path,
) -> None:
    repo = fixture_repo(tmp_path)
    item = candidate(
        repo,
        patch="",
        patch_sha256=digest(""),
    )

    ranked = rank_competitive_evaluation(
        result(repo, (item,))
    )

    assert ranked.status == "no_eligible_candidate"
    assert ranked.winner is None
    assert ranked.approval_payload == ""
    assert ranked.approval_digest == ""
