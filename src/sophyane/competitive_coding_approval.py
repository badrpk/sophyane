"""Fail-closed approval bridge for competitively ranked evidence."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sophyane import hitl
from sophyane.competitive_coding_phase2 import CompetitiveEvaluationResult
from sophyane.competitive_coding_ranking import (
    CompetitiveRankingError,
    CompetitiveRankingResult,
    rank_competitive_evaluation,
)

__all__ = [
    "CompetitiveApprovalRequest",
    "CompetitiveApprovalVerification",
    "CompetitiveApprovalError",
    "request_competitive_approval",
    "verify_competitive_approval",
]


class CompetitiveApprovalError(RuntimeError):
    """Approval evidence is unavailable, malformed, or inconsistent."""


@dataclass(frozen=True)
class CompetitiveApprovalRequest:
    request_id: str
    status: str
    approval_digest: str
    approval_payload: str


@dataclass(frozen=True)
class CompetitiveApprovalVerification:
    approved: bool
    status: str
    request_id: str
    approval_digest: str
    approval_payload: str
    reason: str


def _sha256(text: str) -> str:
    if not isinstance(text, str):
        raise CompetitiveApprovalError("approval payload must be a string")
    try:
        payload = text.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise CompetitiveApprovalError("approval payload is not strict UTF-8") from exc
    return hashlib.sha256(payload).hexdigest()


def _ranked(evaluation: CompetitiveEvaluationResult) -> CompetitiveRankingResult:
    try:
        ranking = rank_competitive_evaluation(evaluation)
    except CompetitiveRankingError as exc:
        raise CompetitiveApprovalError(f"ranking validation failed: {exc}") from exc
    except Exception as exc:
        raise CompetitiveApprovalError(f"ranking failed unexpectedly: {exc}") from exc
    if not isinstance(ranking, CompetitiveRankingResult):
        raise CompetitiveApprovalError("ranking returned an invalid result")
    if ranking.status != "approval_required" or ranking.winner is None:
        raise CompetitiveApprovalError("ranking does not require one approval")
    if not isinstance(ranking.approval_payload, str) or not ranking.approval_payload:
        raise CompetitiveApprovalError("ranking approval payload is invalid")
    if not isinstance(ranking.approval_digest, str) or not ranking.approval_digest:
        raise CompetitiveApprovalError("ranking approval digest is invalid")
    if (
        _sha256(ranking.approval_payload)
        != ranking.approval_digest
    ):
        raise CompetitiveApprovalError(
            "approval payload digest mismatch"
        )

    try:
        payload = json.loads(
            ranking.approval_payload
        )
    except (json.JSONDecodeError, TypeError) as error:
        raise CompetitiveApprovalError(
            "approval payload is invalid JSON"
        ) from error

    expected_keys = {
        "objective",
        "repository",
        "target_name",
        "source_head",
        "baseline_patch_sha256",
        "candidate_id",
        "candidate_patch_sha256",
        "trusted_evidence_digest",
    }

    if (
        not isinstance(payload, dict)
        or set(payload) != expected_keys
    ):
        raise CompetitiveApprovalError(
            "approval payload keys are invalid"
        )

    winner = ranking.winner
    bindings = {
        "candidate_id": winner.candidate_id,
        "candidate_patch_sha256": winner.patch_sha256,
        "source_head": winner.source_head,
    }

    if any(
        not isinstance(value, str)
        or not value
        for value in bindings.values()
    ):
        raise CompetitiveApprovalError(
            "ranking winner binding is invalid"
        )

    if any(
        payload[key] != value
        for key, value in bindings.items()
    ):
        raise CompetitiveApprovalError(
            "approval payload winner binding mismatch"
        )

    return ranking


def _binding(ranking: CompetitiveRankingResult) -> tuple[str, str]:
    winner = ranking.winner
    if winner is None:
        raise CompetitiveApprovalError("ranking winner is missing")
    detail = json.dumps(
        {
            "approval_digest": ranking.approval_digest,
            "approval_payload": ranking.approval_payload,
            "candidate_id": winner.candidate_id,
            "candidate_patch_sha256": winner.patch_sha256,
            "source_head": winner.source_head,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return f"competitive_coding_apply:{ranking.approval_digest}", detail


def _validate_response(
    response: object,
    action: str,
    detail: str,
    request_id: str | None,
) -> dict:
    if not isinstance(response, dict) or response.get("ok") is not True:
        raise CompetitiveApprovalError("HITL response is malformed")
    stored = response.get("request")
    if not isinstance(stored, dict):
        raise CompetitiveApprovalError("HITL request is malformed")
    stored_id = stored.get("id")
    if (
        not isinstance(stored_id, str)
        or not stored_id.strip()
    ):
        raise CompetitiveApprovalError(
            "HITL request id is invalid"
        )
    if request_id is not None and stored_id != request_id:
        raise CompetitiveApprovalError("HITL request id mismatch")
    if stored.get("action") != action:
        raise CompetitiveApprovalError("HITL action mismatch")
    if stored.get("detail") != detail:
        raise CompetitiveApprovalError("HITL detail mismatch")
    if stored.get("risk") != "high":
        raise CompetitiveApprovalError("HITL risk mismatch")
    return stored


def request_competitive_approval(
    evaluation: CompetitiveEvaluationResult,
) -> CompetitiveApprovalRequest:
    ranking = _ranked(evaluation)
    action, detail = _binding(ranking)
    try:
        response = hitl.request_approval(action, detail, risk="high")
    except Exception as exc:
        raise CompetitiveApprovalError(f"HITL request failed: {exc}") from exc
    stored = _validate_response(response, action, detail, None)
    if stored.get("status") != "pending":
        raise CompetitiveApprovalError("new HITL request is not pending")
    return CompetitiveApprovalRequest(
        request_id=stored["id"],
        status="pending",
        approval_digest=ranking.approval_digest,
        approval_payload=ranking.approval_payload,
    )


def verify_competitive_approval(
    evaluation: CompetitiveEvaluationResult,
    request_id: str,
) -> CompetitiveApprovalVerification:
    if not isinstance(request_id, str) or not request_id.strip():
        raise CompetitiveApprovalError("request_id must be a non-empty string")
    ranking = _ranked(evaluation)
    action, detail = _binding(ranking)
    try:
        response = hitl.get_request(request_id)
    except Exception as exc:
        raise CompetitiveApprovalError(f"HITL lookup failed: {exc}") from exc
    stored = _validate_response(response, action, detail, request_id)
    status = stored.get("status")
    if status not in {"pending", "approved", "denied"}:
        raise CompetitiveApprovalError("HITL request status is invalid")
    reasons = {
        "pending": "approval is pending",
        "approved": "approval was granted",
        "denied": "approval was denied",
    }
    return CompetitiveApprovalVerification(
        approved=status == "approved",
        status=status,
        request_id=request_id,
        approval_digest=ranking.approval_digest,
        approval_payload=ranking.approval_payload,
        reason=reasons[status],
    )
