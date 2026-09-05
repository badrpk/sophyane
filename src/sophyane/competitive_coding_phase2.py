"""Phase-2 isolated evaluation for competitive coding proposals."""

from __future__ import annotations

import hashlib

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sophyane.competitive_coding import (
    CompetitiveCodingResult,
    run_competitive_coding,
)
from sophyane.evolution.badrpk_targets import (
    resolve_target,
)
from sophyane.evolution.red_queen_policy import (
    ChallengeRequest,
)
from sophyane.evolution.target_worktree import (
    target_head,
)
from sophyane.evolution.target_evaluator import (
    CandidateEvaluation,
    STATUS_INTERNAL_ERROR,
    TrustedCandidateEvaluation,
    evaluate_candidate_patch,
    evaluate_candidate_patch_from_snapshot,
    evaluate_candidate_patch_from_snapshot_with_trusted_challenges,
    evaluate_candidate_patch_with_trusted_challenges,
)
from sophyane.evolution.trusted_supplemental_executor import (
    TrustedSupplementalEvidence,
    TrustedSupplementalResult,
)
from sophyane.global_txq import GlobalTxqPolicy
from sophyane.recursive_evolution_controller import (
    RecursiveEvolutionError,
)
from sophyane.scoped_candidate_diff import (
    candidate_diff_for_paths,
)

__all__ = [
    "CompetitiveEvaluationCandidate",
    "CompetitiveEvaluationResult",
    "CompetitiveEvaluationError",
    "run_competitive_evaluation",
    "run_competitive_trusted_evaluation",
]


LEGACY_MISSING_BOUNDARY = (
    "trusted_held_out_security_red_queen_gate_adapter"
)
TRUSTED_MISSING_BOUNDARY = (
    "trusted_candidate_ranking_and_approval"
)


class CompetitiveEvaluationError(RuntimeError):
    """Raised when competitive evaluation cannot start safely."""


@dataclass(frozen=True)
class CompetitiveEvaluationCandidate:
    candidate_id: str
    proposal_valid: bool
    proposal_rejection_reason: str
    evaluation_status: str
    evaluation_message: str
    changed_paths: tuple[str, ...]
    validators: tuple[str, ...]
    passed: bool
    trusted_status: str = "NOT_REQUESTED"
    trusted_passed: bool = False
    trusted_evidence: tuple[
        TrustedSupplementalEvidence,
        ...,
    ] = ()
    patch: str = ""
    patch_sha256: str = ""
    source_head: str = ""


@dataclass(frozen=True)
class CompetitiveEvaluationResult:
    objective: str
    repository: Path
    target_name: str
    baseline_paths: tuple[str, ...]
    baseline_patch: str
    txq_policy: GlobalTxqPolicy
    candidates: tuple[
        CompetitiveEvaluationCandidate,
        ...,
    ]
    status: str
    missing_boundary: str
    winner: None = None
    source_head: str = ""
    baseline_patch_sha256: str = ""


def _normalized_baseline_paths(
    paths: Iterable[str],
) -> tuple[str, ...]:
    if isinstance(paths, (str, bytes)):
        raise CompetitiveEvaluationError(
            "baseline_paths must be an iterable of paths"
        )

    try:
        values = tuple(paths)
    except Exception as error:
        raise CompetitiveEvaluationError(
            "baseline_paths could not be enumerated"
        ) from error

    if not values:
        raise CompetitiveEvaluationError(
            "at least one explicit baseline path is required"
        )

    if any(
        not isinstance(value, str)
        or not value.strip()
        for value in values
    ):
        raise CompetitiveEvaluationError(
            "baseline paths must be non-empty strings"
        )

    return tuple(
        sorted(
            set(
                value.strip()
                for value in values
            )
        )
    )


def _normalized_challenges(
    requests: Iterable[ChallengeRequest],
) -> tuple[ChallengeRequest, ...]:
    if isinstance(requests, (str, bytes)):
        raise CompetitiveEvaluationError(
            "challenge_requests must be an iterable "
            "of ChallengeRequest"
        )

    try:
        items = tuple(requests)
    except (TypeError, RuntimeError) as error:
        raise CompetitiveEvaluationError(
            "challenge_requests could not be enumerated"
        ) from error

    if not items:
        raise CompetitiveEvaluationError(
            "challenge_requests must not be empty"
        )

    if any(
        not isinstance(item, ChallengeRequest)
        for item in items
    ):
        raise CompetitiveEvaluationError(
            "every challenge request must be "
            "a ChallengeRequest"
        )

    identifiers = tuple(
        item.challenge_id
        for item in items
    )

    if len(set(identifiers)) != len(identifiers):
        raise CompetitiveEvaluationError(
            "duplicate challenge_id values are not allowed"
        )

    return items


def _patch_digest(patch: str) -> str:
    return hashlib.sha256(
        patch.encode(
            "utf-8",
            errors="strict",
        )
    ).hexdigest()


def _evaluation_record(
    *,
    candidate_id: str,
    proposal_valid: bool,
    proposal_rejection_reason: str,
    evaluation: CandidateEvaluation | None,
    internal_message: str = "",
    trusted_requested: bool = False,
    supplemental: TrustedSupplementalResult | None = None,
    patch: str = "",
    source_head: str = "",
) -> CompetitiveEvaluationCandidate:
    if evaluation is None:
        trusted_status = (
            "NOT_EVALUATED"
            if trusted_requested and not proposal_valid
            else (
                "NOT_EXECUTED"
                if trusted_requested
                else "NOT_REQUESTED"
            )
        )

        return CompetitiveEvaluationCandidate(
            candidate_id=candidate_id,
            proposal_valid=proposal_valid,
            proposal_rejection_reason=(
                proposal_rejection_reason
            ),
            evaluation_status=(
                STATUS_INTERNAL_ERROR
                if internal_message
                else "NOT_EVALUATED"
            ),
            evaluation_message=internal_message,
            changed_paths=(),
            validators=(),
            passed=False,
            trusted_status=trusted_status,
            patch=patch,
            patch_sha256=_patch_digest(patch),
            source_head=source_head,
        )

    validators = tuple(
        run.name
        for run in evaluation.validator_runs
    )

    if not trusted_requested:
        return CompetitiveEvaluationCandidate(
            candidate_id=candidate_id,
            proposal_valid=proposal_valid,
            proposal_rejection_reason=(
                proposal_rejection_reason
            ),
            evaluation_status=evaluation.status,
            evaluation_message=evaluation.message,
            changed_paths=evaluation.changed_paths,
            validators=validators,
            passed=evaluation.passed,
            patch=patch,
            patch_sha256=_patch_digest(patch),
            source_head=source_head,
        )

    if supplemental is None:
        return CompetitiveEvaluationCandidate(
            candidate_id=candidate_id,
            proposal_valid=proposal_valid,
            proposal_rejection_reason=(
                proposal_rejection_reason
            ),
            evaluation_status=evaluation.status,
            evaluation_message=evaluation.message,
            changed_paths=evaluation.changed_paths,
            validators=validators,
            passed=False,
            trusted_status="NOT_EXECUTED",
            patch=patch,
            patch_sha256=_patch_digest(patch),
            source_head=source_head,
        )

    return CompetitiveEvaluationCandidate(
        candidate_id=candidate_id,
        proposal_valid=proposal_valid,
        proposal_rejection_reason=(
            proposal_rejection_reason
        ),
        evaluation_status=evaluation.status,
        evaluation_message=evaluation.message,
        changed_paths=evaluation.changed_paths,
        validators=validators,
        passed=(
            evaluation.passed
            and supplemental.passed
        ),
        trusted_status=supplemental.status,
        trusted_passed=supplemental.passed,
        trusted_evidence=supplemental.evidence,
        patch=patch,
        patch_sha256=_patch_digest(patch),
        source_head=source_head,
    )


def _run_competitive_evaluation(
    *,
    objective: str,
    repository: Path,
    baseline_paths: Iterable[str],
    candidate_provider,
    target_name: str,
    candidate_count: int,
    progress: Callable[[str], None] | None,
    timeout: int,
    challenge_requests: tuple[
        ChallengeRequest,
        ...,
    ] | None,
) -> CompetitiveEvaluationResult:
    resolved = Path(repository).expanduser().resolve()
    selected_paths = _normalized_baseline_paths(
        baseline_paths
    )
    report = progress or (lambda _message: None)
    trusted_requested = challenge_requests is not None

    target = resolve_target(
        name=target_name,
        harness_repo=resolved,
        explicit_repo=resolved,
        require_exists=True,
    )
    evaluated_head = target_head(target)

    try:
        baseline_patch = candidate_diff_for_paths(
            resolved,
            selected_paths,
        )
    except RecursiveEvolutionError as error:
        raise CompetitiveEvaluationError(
            f"baseline construction failed: {error}"
        ) from error

    phase1: CompetitiveCodingResult = (
        run_competitive_coding(
            objective=objective,
            repository=resolved,
            candidate_provider=candidate_provider,
            candidate_count=candidate_count,
            apply_winner=False,
            progress=report,
        )
    )

    records: list[
        CompetitiveEvaluationCandidate
    ] = []

    for proposal in phase1.candidates:
        if not proposal.valid:
            records.append(
                _evaluation_record(
                    candidate_id=proposal.candidate_id,
                    proposal_valid=False,
                    proposal_rejection_reason=(
                        proposal.rejection_reason
                    ),
                    evaluation=None,
                    trusted_requested=trusted_requested,
                    patch=proposal.patch,
                    source_head=evaluated_head,
                )
            )
            continue

        report(
            f"Evaluating {proposal.candidate_id}"
        )

        try:
            supplemental = None

            if trusted_requested:
                assert challenge_requests is not None

                if baseline_patch:
                    composite: TrustedCandidateEvaluation = (
                        evaluate_candidate_patch_from_snapshot_with_trusted_challenges(
                            target,
                            baseline_patch,
                            proposal.patch,
                            challenge_requests,
                            timeout=timeout,
                        )
                    )
                else:
                    composite = (
                        evaluate_candidate_patch_with_trusted_challenges(
                            target,
                            proposal.patch,
                            challenge_requests,
                            timeout=timeout,
                        )
                    )

                evaluation = composite.candidate
                supplemental = composite.supplemental

            elif baseline_patch:
                evaluation = (
                    evaluate_candidate_patch_from_snapshot(
                        target,
                        baseline_patch,
                        proposal.patch,
                        timeout=timeout,
                    )
                )

            else:
                evaluation = evaluate_candidate_patch(
                    target,
                    proposal.patch,
                    timeout=timeout,
                )

        except Exception as error:
            records.append(
                _evaluation_record(
                    candidate_id=proposal.candidate_id,
                    proposal_valid=True,
                    proposal_rejection_reason="",
                    evaluation=None,
                    internal_message=(
                        f"{type(error).__name__}: {error}"
                    ),
                    trusted_requested=trusted_requested,
                    patch=proposal.patch,
                    source_head=evaluated_head,
                )
            )
            continue

        records.append(
            _evaluation_record(
                candidate_id=proposal.candidate_id,
                proposal_valid=True,
                proposal_rejection_reason="",
                evaluation=evaluation,
                trusted_requested=trusted_requested,
                supplemental=supplemental,
                patch=proposal.patch,
                source_head=evaluated_head,
            )
        )

    missing_boundary = (
        TRUSTED_MISSING_BOUNDARY
        if trusted_requested
        else LEGACY_MISSING_BOUNDARY
    )

    report(
        "Competitive Phase 2 stopped before "
        + missing_boundary
    )

    final_head = target_head(target)

    if final_head != evaluated_head:
        raise CompetitiveEvaluationError(
            "repository HEAD changed during competitive evaluation"
        )

    return CompetitiveEvaluationResult(
        objective=phase1.objective,
        repository=resolved,
        target_name=target.name,
        baseline_paths=selected_paths,
        baseline_patch=baseline_patch,
        txq_policy=phase1.txq_policy,
        candidates=tuple(records),
        status="fail_closed",
        missing_boundary=missing_boundary,
        winner=None,
        source_head=evaluated_head,
        baseline_patch_sha256=_patch_digest(
            baseline_patch
        ),
    )


def run_competitive_evaluation(
    *,
    objective: str,
    repository: Path,
    baseline_paths: Iterable[str],
    candidate_provider,
    target_name: str = "sophyane",
    candidate_count: int = 2,
    progress: Callable[[str], None] | None = None,
    timeout: int = 300,
) -> CompetitiveEvaluationResult:
    """Run legacy Phase-2 evaluation without trusted supplementals."""

    return _run_competitive_evaluation(
        objective=objective,
        repository=repository,
        baseline_paths=baseline_paths,
        candidate_provider=candidate_provider,
        target_name=target_name,
        candidate_count=candidate_count,
        progress=progress,
        timeout=timeout,
        challenge_requests=None,
    )


def run_competitive_trusted_evaluation(
    *,
    objective: str,
    repository: Path,
    baseline_paths: Iterable[str],
    candidate_provider,
    challenge_requests: Iterable[ChallengeRequest],
    target_name: str = "sophyane",
    candidate_count: int = 2,
    progress: Callable[[str], None] | None = None,
    timeout: int = 300,
) -> CompetitiveEvaluationResult:
    """Run Phase-2 ordinary and trusted evidence gates."""

    requests = _normalized_challenges(
        challenge_requests
    )

    return _run_competitive_evaluation(
        objective=objective,
        repository=repository,
        baseline_paths=baseline_paths,
        candidate_provider=candidate_provider,
        target_name=target_name,
        candidate_count=candidate_count,
        progress=progress,
        timeout=timeout,
        challenge_requests=requests,
    )
