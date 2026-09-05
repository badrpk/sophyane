"""Read-only deterministic competitive evidence ranking."""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from sophyane.competitive_coding_phase2 import (
    CompetitiveEvaluationCandidate,
    CompetitiveEvaluationResult,
)
from sophyane.scoped_candidate_diff import candidate_diff_for_paths

__all__ = [
    "CompetitiveRankedCandidate",
    "CompetitiveRankingResult",
    "CompetitiveRankingError",
    "rank_competitive_evaluation",
]


class CompetitiveRankingError(RuntimeError):
    """Stored competitive evidence cannot be trusted."""


@dataclass(frozen=True)
class CompetitiveRankedCandidate:
    candidate_id: str
    patch: str
    patch_sha256: str
    source_head: str
    trusted_evidence_digest: str


@dataclass(frozen=True)
class CompetitiveRankingResult:
    status: str
    eligible_candidate_ids: tuple[str, ...]
    winner: CompetitiveRankedCandidate | None
    approval_payload: str
    approval_digest: str
    reason: str


def _sha256(text: str) -> str:
    try:
        payload = text.encode("utf-8", errors="strict")
    except (AttributeError, UnicodeEncodeError) as exc:
        raise CompetitiveRankingError("text is not strict UTF-8") from exc
    return hashlib.sha256(payload).hexdigest()


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _repository(result: CompetitiveEvaluationResult) -> Path:
    recorded = Path(result.repository)
    resolved = recorded.expanduser().resolve()
    if not resolved.is_dir():
        raise CompetitiveRankingError("repository does not exist")
    check = subprocess.run(
        ("git", "-C", str(resolved), "rev-parse", "--show-toplevel"),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if check.returncode or Path(check.stdout.strip()).resolve() != resolved:
        raise CompetitiveRankingError("repository identity mismatch")
    return resolved


def _head(repository: Path) -> str:
    check = subprocess.run(
        ("git", "-C", str(repository), "rev-parse", "HEAD"),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if check.returncode:
        raise CompetitiveRankingError("repository HEAD is unavailable")
    return check.stdout.strip()


def _evidence_digest(candidate: CompetitiveEvaluationCandidate) -> str:
    return _sha256(_canonical([asdict(item) for item in candidate.trusted_evidence]))


def _trusted(candidate: CompetitiveEvaluationCandidate) -> bool:
    if not candidate.trusted_evidence:
        return False
    for item in candidate.trusted_evidence:
        if not (
            item.executed
            and item.passed
            and not item.timed_out
            and item.returncode == 0
            and item.rejection_reason is None
            and isinstance(item.family, str)
            and bool(item.family)
            and isinstance(item.challenge_id, str)
            and bool(item.challenge_id)
            and isinstance(item.evaluator_identity, str)
            and bool(item.evaluator_identity)
            and isinstance(item.test_path, str)
            and bool(item.test_path)
        ):
            return False
    return True


def _eligible(candidate: CompetitiveEvaluationCandidate) -> bool:
    return bool(
        candidate.proposal_valid
        and candidate.evaluation_status == "PASS"
        and candidate.passed
        and candidate.trusted_status == "PASS"
        and candidate.trusted_passed
        and candidate.patch
        and candidate.patch_sha256
        and _trusted(candidate)
    )


def _validate(
    result: CompetitiveEvaluationResult,
) -> tuple[Path, tuple[CompetitiveEvaluationCandidate, ...]]:
    if not isinstance(result, CompetitiveEvaluationResult):
        raise CompetitiveRankingError("expected CompetitiveEvaluationResult")
    if result.status != "fail_closed":
        raise CompetitiveRankingError("result status is not fail_closed")
    if result.missing_boundary != "trusted_candidate_ranking_and_approval":
        raise CompetitiveRankingError("result boundary is not rankable")
    if result.winner is not None:
        raise CompetitiveRankingError("result already has a winner")
    repository = _repository(result)
    if not result.source_head or _head(repository) != result.source_head:
        raise CompetitiveRankingError("result source HEAD mismatch")
    baseline = candidate_diff_for_paths(repository, result.baseline_paths)
    if baseline != result.baseline_patch:
        raise CompetitiveRankingError("baseline text mismatch")
    if _sha256(baseline) != result.baseline_patch_sha256:
        raise CompetitiveRankingError("baseline digest mismatch")
    candidates = tuple(result.candidates)
    for candidate in candidates:
        if candidate.source_head != result.source_head:
            raise CompetitiveRankingError(
                f"candidate {candidate.candidate_id} source HEAD mismatch"
            )
        if (
            not isinstance(candidate.patch, str)
            or not isinstance(candidate.patch_sha256, str)
            or _sha256(candidate.patch)
            != candidate.patch_sha256
        ):
            raise CompetitiveRankingError(
                f"candidate {candidate.candidate_id} "
                "patch digest mismatch"
            )
    return repository, candidates


def rank_competitive_evaluation(
    result: CompetitiveEvaluationResult,
) -> CompetitiveRankingResult:
    try:
        repository, candidates = _validate(result)
    except CompetitiveRankingError:
        raise
    except Exception as exc:
        raise CompetitiveRankingError(f"stored evidence validation failed: {exc}") from exc

    eligible = tuple(candidate for candidate in candidates if _eligible(candidate))
    identifiers = tuple(sorted(candidate.candidate_id for candidate in eligible))
    if not eligible:
        return CompetitiveRankingResult(
            "no_eligible_candidate", (), None, "", "", "no candidate passed every gate"
        )
    if len(eligible) != 1:
        return CompetitiveRankingResult(
            "ambiguous",
            identifiers,
            None,
            "",
            "",
            "multiple candidates passed every gate",
        )

    candidate = eligible[0]
    evidence_digest = _evidence_digest(candidate)
    ranked = CompetitiveRankedCandidate(
        candidate_id=candidate.candidate_id,
        patch=candidate.patch,
        patch_sha256=candidate.patch_sha256,
        source_head=candidate.source_head,
        trusted_evidence_digest=evidence_digest,
    )
    payload = _canonical(
        {
            "objective": result.objective,
            "repository": str(repository),
            "target_name": result.target_name,
            "source_head": result.source_head,
            "baseline_patch_sha256": result.baseline_patch_sha256,
            "candidate_id": candidate.candidate_id,
            "candidate_patch_sha256": candidate.patch_sha256,
            "trusted_evidence_digest": evidence_digest,
        }
    )
    return CompetitiveRankingResult(
        "approval_required",
        identifiers,
        ranked,
        payload,
        _sha256(payload),
        "one candidate passed every gate",
    )
